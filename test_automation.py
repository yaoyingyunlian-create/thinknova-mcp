"""Offline tests; no MCP calls, dependencies installed, schedules or publications."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch
import automation
import health
import secure_state
import bootstrap
from automation_client import Client
import urllib.error


class HealthTests(unittest.TestCase):
    def test_browser_launch_failure_blocks_browser_capability(self):
        with patch.object(health, 'verify_files', return_value=True), patch.object(health, 'chromium_probe', return_value=False):
            result=health.report()
        self.assertEqual(result['capabilities']['browser_publishing'],'fail')
        self.assertEqual(next(x for x in result['checks'] if x['name']=='chromium_runtime')['status'],'fail')
        self.assertEqual(next(x for x in result['checks'] if x['name']=='account')['status'],'unknown')

    def test_network_failure_is_unknown_not_latest(self):
        with patch.object(bootstrap,'git',side_effect=RuntimeError('network')),patch.object(health,'chromium_probe',return_value=True):result=health.report(online=True)
        value=next(x for x in result['checks'] if x['name']=='github_version')
        self.assertEqual(value['status'],'unknown');self.assertIsNone(value['update_available'])

    def test_probe_checks_return_code_not_executable_file(self):
        with patch.object(health.subprocess,'run',return_value=subprocess.CompletedProcess([],1)) as call:
            self.assertFalse(health.chromium_probe())
            self.assertIn('chromium.launch',call.call_args.args[0][-1])

    def test_manifest_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);(p/'manifest.json').write_text(json.dumps({'files':[{'path':'../outside','sha256':'0'*64}]}),encoding='utf-8')
            self.assertFalse(health.verify_files(p))


class ControlledPlanTests(unittest.TestCase):
    def test_transport_retry_preserves_paid_intent(self):
        client=Client({'execution_token':'a'*64});client.session='session'
        args={'prompt':'A cafe','client_request_id':'run:shot:0','automation_run_id':'run_test'}
        with patch.object(client,'post',side_effect=[urllib.error.URLError('offline'),({'result':{'structuredContent':{'task_id':'task_same'}}},{})]) as post:
            self.assertEqual(client.tool('generate_video',args)['task_id'],'task_same')
            self.assertEqual(post.call_args_list[0].args[1]['params']['arguments'],post.call_args_list[1].args[1]['params']['arguments'])

    def test_expired_session_is_reinitialized_once(self):
        client=Client({'execution_token':'a'*64});client.session='old'
        responses=[RuntimeError('DEVICE_HTTP_404'),({'result':{}},{'Mcp-Session-Id':'new'}),({'result':{'structuredContent':{'available_credits':20}}},{})]
        with patch.object(client,'post',side_effect=responses):self.assertEqual(client.tool('get_balance')['available_credits'],20)
        self.assertEqual(client.session,'new')
    def test_accepts_only_content_data(self):
        value={'title':'Cafe','description':'A real shop','shots':[{'prompt':'Warm interior'}]}
        self.assertEqual(automation.validate_plan(value),value)
        for extra in ({'command':'publish'}, {'video':'../../secret'}):
            with self.assertRaises(RuntimeError):automation.validate_plan({**value,**extra})
        with self.assertRaises(RuntimeError):automation.validate_plan({**value,'shots':[{'prompt':'A','shell':'cmd'}]})

    def test_plan_requires_bounded_shots(self):
        for shots in ([],[{'prompt':'A'}]*5,[{'prompt':''}]):
            with self.assertRaises(RuntimeError):automation.validate_plan({'title':'A','description':'B','shots':shots})

    def test_reference_route_preserves_legacy_and_rejects_unselected_frame(self):
        rules = {'authorized_asset_ids': ['asset_A']}
        self.assertEqual(automation.shot_tool({'prompt': 'old'}, rules), ('generate_video', {}))
        self.assertEqual(automation.shot_tool({'prompt': 'new', 'first_frame_asset_id': None}, {}), ('generate_video', {}))
        with self.assertRaisesRegex(RuntimeError, 'REFERENCE_FIRST_FRAME_REQUIRED'):
            automation.shot_tool({'first_frame_asset_id': None}, rules)
        with self.assertRaisesRegex(RuntimeError, 'FIRST_FRAME_NOT_AUTHORIZED'):
            automation.shot_tool({'first_frame_asset_id': 'asset_B'}, rules)

    def test_first_frame_used_by_quote_and_creation(self):
        run_no = 'run_' + 'a' * 24
        rules = {'version': 1, 'effective_rules': {'authorized_asset_ids': ['asset_A']}}
        plan = {'title': 'A', 'description': 'B', 'shots': [{'prompt': 'Pan right', 'first_frame_asset_id': 'asset_A'}]}
        balance = {'generation_available': True, 'available_credits': 100, 'quote_mode_supported': True}
        quote = {'generation_quote': {'quote_only': True, 'creates_task': False, 'reserves_credits': False, 'estimated_credits': 8}}
        client = Mock()
        client.tool.side_effect = [rules, balance, quote, RuntimeError('TEST_STOP')]
        with tempfile.TemporaryDirectory() as folder, patch.object(automation, 'STATE', Path(folder)), patch.object(
            automation, 'connected_report', return_value={'automation_ready': True}
        ), patch.object(automation, 'make_plan', return_value=plan):
            with self.assertRaisesRegex(RuntimeError, 'TEST_STOP'):
                automation.execute(client, {'run_no': run_no, 'grant': {'rules_version': 1}})
        request = client.tool.call_args_list[2].args[1]['quote_request']
        self.assertEqual(request['tool'], 'animate_image')
        self.assertEqual(request['arguments']['reference_asset_ids'], ['asset_A'])
        self.assertEqual(client.tool.call_args_list[3].args, ('animate_image', {**request['arguments'], 'max_credits': 8}))

    def test_delivery_refuses_untrusted_urls(self):
        for url in ('http://api.thinknova.top/video','https://evil.example/video','https://secret@api.thinknova.top/file'):
            with self.assertRaises(RuntimeError):automation.download(url,Path('unused.mp4'))

    @unittest.skipUnless(os.name=='nt','Windows DPAPI only')
    def test_dpapi_roundtrip_never_writes_plaintext(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.dpapi';value={'execution_token':'synthetic-test-secret'}
            secure_state.save(p,value)
            self.assertNotIn(b'synthetic-test-secret',p.read_bytes())
            self.assertEqual(secure_state.load(p),value)


if __name__=='__main__':unittest.main()
