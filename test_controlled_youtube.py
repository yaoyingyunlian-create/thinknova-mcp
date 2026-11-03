"""Synthetic YouTube API; never authenticates, uploads or publishes real content."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
import automation_client
import secure_state

ROOT=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('controlled_youtube',ROOT/'publish/youtube/upload.py')
upload=importlib.util.module_from_spec(spec);spec.loader.exec_module(upload)


class Response:
    def __init__(self,value):self.value=value
    def execute(self):return self.value


class FakeYouTube:
    def __init__(self):self.insertions=0;self.privacy_writes=[];self.body=None
    def videos(self):return self
    def insert(self,**kw):
        self.insertions+=1;self.body=kw['body'];self.privacy_writes.append(self.body['status']['privacyStatus'])
        return self
    def next_chunk(self):return None,{'id':'Abcdef12345'}
    def list(self,**kw):return Response({'items':[self.body]})
    def update(self,**kw):
        status=kw['body'].get('status')
        if status:self.body['status'].update(status);self.privacy_writes.append(self.body['status']['privacyStatus'])
        return Response({})


class PublisherTests(unittest.TestCase):
    def invoke(self,root,api,expected='UC'+'a'*22,denied=False):
        video=root/'clip.mp4';video.write_bytes(b'synthetic-fixture')
        job=root/'job.json';job.write_text(json.dumps({'video':str(video),'title':'Cafe','description':'Real shop','privacy':'public','aigc':True,'expected_channel_id':expected,'automation_run_id':'run_'+'a'*24,'automation_steps':{'task_0':'task_fixture'}}),encoding='utf-8')
        module=types.ModuleType('googleapiclient.http');module.MediaFileUpload=lambda *a,**k: object()
        with patch.dict(sys.modules,{'googleapiclient.http':module}),patch.object(upload.yt_common,'youtube',return_value=api),patch.object(upload.yt_common,'my_channel',return_value={'id':'UC'+'a'*22,'title':'Fixture','handle':'fixture','subs':0,'videos':0}),patch.object(upload,'run_check',return_value=0),patch.object(upload,'append_log'),patch.object(upload.time,'sleep'),patch.object(secure_state,'load',return_value={'execution_token':'a'*64}),patch.object(automation_client.Client,'receipt',side_effect=RuntimeError('AUTOMATION_INACTIVE') if denied else None) as permission,patch.object(sys,'argv',['upload.py',str(job),'--execute']):
            result=upload.main()
            return result,permission.call_count

    def test_private_staging_before_final_authorization(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeYouTube();code,calls=self.invoke(Path(d),api)
            self.assertEqual(code,0);self.assertEqual(calls,1);self.assertEqual(api.privacy_writes[0],'private');self.assertEqual(api.privacy_writes[-1],'public')
            receipt=json.loads((Path(d)/'job.json.receipt.json').read_text(encoding='utf-8'))
            self.assertEqual(receipt['state'],'verified')

    def test_revoke_during_private_upload_prevents_publication(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeYouTube()
            with self.assertRaisesRegex(RuntimeError,'AUTOMATION_INACTIVE'):self.invoke(Path(d),api,denied=True)
            self.assertNotIn('public',api.privacy_writes)

    def test_existing_upload_marker_prevents_duplicate(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'job.json.receipt.json').write_text('{"state":"uploading"}',encoding='utf-8')
            api=FakeYouTube();code,_=self.invoke(root,api)
            self.assertEqual(code,2);self.assertEqual(api.insertions,0)

    def test_channel_mismatch_never_uploads(self):
        with tempfile.TemporaryDirectory() as d:
            api=FakeYouTube();code,_=self.invoke(Path(d),api,expected='UC'+'b'*22)
            self.assertEqual(code,2);self.assertEqual(api.insertions,0)


if __name__=='__main__':unittest.main()
