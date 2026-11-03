"""Restricted ThinkNova device and MCP client. Tokens remain in the local runner."""
from __future__ import annotations
import json
import urllib.request
import urllib.error

BASE = 'https://api.thinknova.top'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('REDIRECT_REFUSED')


class Client:
    def __init__(self, secrets: dict):
        self.secrets = secrets; self.session = None; self.lease = ''; self.sequence = 0
        self.opener = urllib.request.build_opener(NoRedirect())

    def post(self, path: str, value: dict, execution: bool = True) -> tuple[dict, object]:
        token = self.secrets['execution_token' if execution else 'telemetry_token']
        headers = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json, text/event-stream', 'MCP-Protocol-Version': '2025-06-18'}
        if self.session: headers['Mcp-Session-Id'] = self.session
        if self.lease: headers['X-Automation-Lease'] = self.lease
        req = urllib.request.Request(BASE + path, json.dumps(value).encode('utf-8'), headers=headers)
        try:
            with self.opener.open(req, timeout=45) as response:
                return json.loads(response.read(2*1024*1024)), response.headers
        except urllib.error.HTTPError as exc:
            # The remote body could contain a signed URL or other sensitive data.
            raise RuntimeError('DEVICE_HTTP_' + str(exc.code)) from None

    def tool(self, name: str, args: dict | None = None, _retry: bool = False) -> dict:
        if not self.session:
            value, headers = self.post('/mcp', {'jsonrpc': '2.0', 'id': 0, 'method': 'initialize', 'params': {'protocolVersion': '2025-06-18', 'capabilities': {}, 'clientInfo': {'name': 'ThinkNova controlled runner', 'version': '1.0.0'}}})
            self.session = headers.get('Mcp-Session-Id')
            if not self.session or 'error' in value: raise RuntimeError('MCP_INITIALIZE_FAILED')
        self.sequence += 1
        try:
            value, _ = self.post('/mcp', {'jsonrpc':'2.0', 'id':self.sequence, 'method':'tools/call', 'params':{'name':name,'arguments':args or {}}})
        except (urllib.error.URLError, TimeoutError):
            if _retry: raise
            return self.tool(name,args,True)  # Same intent/request ID; never invent another paid request.
        except RuntimeError as exc:
            if str(exc) != 'DEVICE_HTTP_404' or _retry: raise
            self.session = None
            return self.tool(name,args,True)
        if 'error' in value: raise RuntimeError('MCP_REQUEST_FAILED')
        result = value.get('result', {})
        if result.get('isError'):
            code = result.get('structuredContent', {}).get('reason_code', 'MCP_TOOL_FAILED')
            raise RuntimeError(code if isinstance(code,str) and code.replace('_','').isalnum() else 'MCP_TOOL_FAILED')
        return result['structuredContent']

    def claim(self) -> dict:
        value, _ = self.post('/mcp/device/claim', {})
        result = value['data']; self.lease = result.get('lease', ''); return result

    def receipt(self, run_no: str, steps: dict, status='running', error_code=None):
        body = {'steps':steps,'status':status}
        if error_code: body['error_code']=error_code
        self.post('/mcp/device/runs/' + run_no + '/receipt', body)
