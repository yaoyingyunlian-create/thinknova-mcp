"""Sparse-media, quote, encoding and policy regressions. All remote calls are simulated."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from dialogue_encoding import validate_text, read_json
from day_preparation import prepare_assets
from quality_policy import agreement, receipt
from render import check, assemble
import clip_recovery


class SparseDeliveryTests(unittest.TestCase):
    def tearDown(self):
        check.RELAXED = False
        check.FAILS.clear(); check.WARNS.clear()

    def test_encoding_preserves_chinese_and_other_languages(self):
        for text in ['Exact Mandarin dialogue: 你想试哪一款？', '日本語の台詞', 'Thai: สวัสดี', 'English: hello']:
            self.assertEqual(validate_text(text), text)
        for text in ['Exact Mandarin dialogue: ߰λһŴĿռôȽϣ', 'broken\ufffd', '\ud800']:
            with self.assertRaisesRegex(ValueError, 'DIALOGUE_ENCODING_INVALID'):
                validate_text(text)
        with self.assertRaisesRegex(ValueError, 'DIALOGUE_ENCODING_INVALID'):
            validate_text('staff说：「߰λһŴĿռôȽϣ」', 'zh')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '店铺计划.json'
            path.write_bytes('中文'.encode('gbk'))
            with self.assertRaisesRegex(ValueError, 'DAY_PLAN_UTF8_SOURCE_INVALID'):
                read_json(path)

    def test_agreement_boundaries_and_unknown_status(self):
        for score, state in [(0.29,'fail'),(0.3,'warn'),(0.79,'warn'),(0.8,'pass'),(None,'warn')]:
            self.assertEqual(agreement(score)[0], state)
        result = receipt({'version':'58'}, [{'code':'SPEECH_CHECK_PENDING','message':'unavailable'}])
        self.assertEqual(result['speech_status'], 'unknown')
        self.assertFalse(result['checks_completed'])

    def test_sparse_rotation_warns_but_legacy_still_blocks(self):
        from store_editorial import validate_rotation
        profile={'audiences':['shopper'],'pain_points':[],'features':['service'],'scenes':['generic'],'questions':[]}
        row={'date':'2026-11-19','row':'shopper','col':'service','scene':'generic',
             'format':'shop_visit','opening':'A concrete opening','opening_visual':'An ongoing action'}
        old={**row,'date':'2026-11-18'}
        warnings=[]
        self.assertEqual(validate_rotation([row],[old],profile,3,'59',warnings),[row])
        self.assertTrue(warnings)
        with self.assertRaisesRegex(ValueError,'PLAN_CONSECUTIVE_REPEAT'):
            validate_rotation([row],[old],profile,3,'54')

    def test_only_unusable_media_blocks_under_new_policy(self):
        check.RELAXED = True
        for code in ['FILM_PACE_OUTSIDE_LIMIT','FILM_SENTENCE_PAUSE','FILM_SEGMENT_SPEECH_GAP','FILM_STATIC_SCENE','SPEECH_CHECK_PENDING']:
            check.fail(code, 'fixture')
        self.assertEqual(check.FAILS, [])
        for code in ['MEDIA_DECODE_FAILED','MEDIA_BLACK','S3_NEAR_SILENT','FILM_DIALOGUE_MISMATCH']:
            check.fail(code, 'fixture')
        self.assertEqual(len(check.FAILS),4)

    def test_boundary_trim_preserves_speech_and_sync(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(assemble,'speech_chunks',return_value=[(1.2,13.8)]), \
             patch.object(assemble,'run_ff') as ff:
            _, duration, report = assemble.trim_store_blank('ff','clip.mp4',15,directory,1,3)
            self.assertAlmostEqual(duration,13.1)
            self.assertAlmostEqual(report['start_trim'],0.95)
            filters = ff.call_args.args[1]
            self.assertIn('atrim=start=0.95:end=14.05', filters[filters.index('-filter_complex')+1])

    def test_preparation_reuses_ambiguous_request_and_counts_budget(self):
        graph = [dict(slot='slot_staff',role='staff',tool='generate_image',ratio='1:1',references=[],prompt='A fictional staff sheet'),
                 dict(slot='slot_frame_0',role='first_frame',tool='edit_image',ratio='9:16',references=['slot_staff'],prompt='店员正在服务')]
        original = {'asset_preparation':graph,'asset_bindings':{},'project_key':'shop'}
        class FakeClient:
            def __init__(self): self.plan=copy.deepcopy(original); self.created={}; self.ambiguous=True
            def tool(self,name,args=None):
                if name == 'get_balance': return {'available_credits':100}
                if name == 'get_task': return {'status':'succeeded'}
                request=args['client_request_id']
                self.created.setdefault(request, 'task_'+str(len(self.created)))
                if self.ambiguous:
                    self.ambiguous=False
                    raise RuntimeError('CONNECTION_CLOSED')
                return {'task_id':self.created[request]}
            def receipt(self,*args,**kwargs): pass
            def post(self,url,payload):
                if url.endswith('/configuration'):
                    return {'data':{'remaining_credits':100}},{}
                for slot,task in payload['bindings'].items(): self.plan['asset_bindings'][slot]='asset_'+task
                return {'data':{'status':'ready','plan':copy.deepcopy(self.plan)}},{}
        def atomic(path,value): Path(path).write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')
        def quote(client,tool,args,balance): return {**args,'max_credits':6}
        with tempfile.TemporaryDirectory() as directory:
            client=FakeClient(); claim={'run_no':'run_fixture','steps':{}}
            with self.assertRaisesRegex(RuntimeError,'CONNECTION_CLOSED'):
                prepare_assets(client,claim,copy.deepcopy(original),directory,20,quote,atomic)
            plan=prepare_assets(client,claim,copy.deepcopy(original),directory,20,quote,atomic)
            self.assertEqual(len(client.created),2)
            self.assertEqual(plan['preparation_credits'],12)
            self.assertEqual(len(plan['asset_bindings']),2)
        with tempfile.TemporaryDirectory() as directory:
            client=FakeClient();client.ambiguous=False
            with self.assertRaisesRegex(RuntimeError,'DAY_PLAN_OVER_BUDGET'):
                prepare_assets(client,{'run_no':'run_fixture','steps':{}},copy.deepcopy(original),directory,6,quote,atomic)
            self.assertEqual(len(client.created),1)
        with tempfile.TemporaryDirectory() as directory:
            client=FakeClient();client.ambiguous=False
            forecast=copy.deepcopy(original);forecast['minimum_video_credits']=100
            with self.assertRaisesRegex(RuntimeError,'DAY_PLAN_OVER_BUDGET'):
                prepare_assets(client,{'run_no':'run_fixture','steps':{}},forecast,directory,20,quote,atomic)
            self.assertEqual(len(client.created),0)

    def test_unknown_speech_returns_original_without_paid_generation(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(clip_recovery,'inspect_speech',side_effect=RuntimeError('crash')):
            original=Path(directory)/'original.mp4';original.write_bytes(b'fixture')
            class NoPaidCalls:
                def tool(self,*args): raise AssertionError('unexpected paid call')
            result, evidence=clip_recovery.recover_clip(NoPaidCalls(),{}, {'quality_policy':{'version':'58'},'segments':[{'subs':['你好']}]},
                0,{},original,{},lambda:None,None,None,lambda p,v:p.write_text(json.dumps(v),encoding='utf-8'),0)
            self.assertEqual(result,original)
            self.assertEqual(evidence['speech_status'],'unknown')

    def test_two_local_mismatches_allow_one_budgeted_recovery_then_caption_fallback(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shot0.mp4';path.write_bytes(b'original')
            path.with_name('shot0-recovery.mp4').write_bytes(b'recovery fixture')
            client=Mock()
            def tool(name,args=None):
                return {'get_balance':{},'animate_image':{'task_id':'task_recovery'},'get_task':{'status':'succeeded'}}[name]
            client.tool.side_effect=tool
            state={}
            plan={'quality_policy':{'version':'58'},'segments':[{'subs':['正确台词']}]}
            claim={'grant':{'daily_budget':100}}
            args={'client_request_id':'run_fixture:store:0','prompt':'Original verified dialogue'}
            def atomic(file,value):file.write_text(json.dumps(value),encoding='utf-8')
            with patch.object(clip_recovery,'inspect_speech',return_value={'agreement':0.05,'transcript':'wrong'}):
                result,report=clip_recovery.recover_clip(client,claim,plan,0,args,path,state,lambda:None,
                    lambda c,t,a,b:{**a,'max_credits':20},None,atomic,60)
            self.assertEqual(len(report['attempts']),3)
            self.assertEqual(result,path)
            self.assertEqual(report['warning'],'SPEECH_REVIEW_REQUIRED')
            self.assertEqual(path.read_bytes(),b'original')
            calls=[call for call in client.tool.call_args_list if call.args[0]=='animate_image']
            self.assertEqual(len(calls),1)
            self.assertEqual(calls[0].args[1]['client_request_id'],'run_fixture:store:0:retry:1')
            self.assertTrue(result.is_file())

    def test_inventory_rejects_expired_or_attempted_and_reserves_once(self):
        from film_inventory import reserve
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);folder=root/'runs'/'run_old';folder.mkdir(parents=True)
            video=folder/'final.mp4';video.write_bytes(b'synthetic inventory')
            Path(str(video)+'.film.json').write_text(json.dumps({'machine_check':'pass','sha256':hashlib.sha256(video.read_bytes()).hexdigest()}),encoding='utf-8')
            target={'youtube':{'expected_channel_id':'UC_fixture','title':'old title'}}
            job=folder/'publish.json';job.write_text(json.dumps({'platforms':target}),encoding='utf-8')
            summary={'project_key':'shop','source_date':'2026-11-17','output':str(video),'publish_job':str(job),
                     'activity_content':True,'valid_until':'2026-11-18'}
            meta=folder/'review-ready.json';meta.write_text(json.dumps(summary),encoding='utf-8')
            self.assertIsNone(reserve(root,'shop','2026-11-19',target,'run_new'))
            summary['activity_content']=False;meta.write_text(json.dumps(summary),encoding='utf-8')
            state=folder/'state.json';state.write_text(json.dumps({'publication_started':'yes'}),encoding='utf-8')
            self.assertIsNone(reserve(root,'shop','2026-11-19',target,'run_new'))
            state.write_text('{}',encoding='utf-8')
            self.assertIsNone(reserve(root,'another','2026-11-19',target,'run_new'))
            self.assertIsNotNone(reserve(root,'shop','2026-11-19',target,'run_new'))
            self.assertIsNone(reserve(root,'shop','2026-11-19',target,'run_other'))

    def test_ambiguous_recovery_reuses_saved_quote_when_balance_changed(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shot.mp4';path.write_bytes(b'original')
            repaired=Path(directory)/'shot-recovery.mp4';repaired.write_bytes(b'recovered')
            saved={'prompt':'Previously approved exact request','client_request_id':'run:store:0:retry:1','max_credits':20}
            path.with_suffix('.recovery-request.json').write_text(json.dumps(saved),encoding='utf-8')
            client=Mock()
            client.tool.side_effect=lambda name,args=None: {'animate_image':{'task_id':'task_existing'},'get_task':{'status':'succeeded'}}[name]
            assessments=[{'agreement':0.01,'transcript':'wrong'}]*2+[{'agreement':0.9,'transcript':'correct'}]
            quote=Mock(side_effect=AssertionError('An ambiguous request must reuse its original quote'))
            with patch.object(clip_recovery,'inspect_speech',side_effect=assessments):
                result,_=clip_recovery.recover_clip(client,{'grant':{'daily_budget':20}},
                    {'quality_policy':{'version':'58'},'segments':[{'subs':['correct']}]},0,
                    {'prompt':'new intent','client_request_id':'run:store:0'},path,{},lambda:None,
                    quote,None,lambda file,value:file.write_text(json.dumps(value),encoding='utf-8'),20)
            self.assertEqual(result,repaired)
            self.assertEqual(client.tool.call_args_list[0].args,('animate_image',saved))
            quote.assert_not_called()

    def test_recovery_cannot_exceed_the_lower_run_budget(self):
        from unittest.mock import Mock
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'shot.mp4';path.write_bytes(b'original')
            client=Mock();client.tool.return_value={}
            def atomic(file,value):file.write_text(json.dumps(value),encoding='utf-8')
            with patch.object(clip_recovery,'inspect_speech',return_value={'agreement':0.01,'transcript':'wrong'}):
                result,report=clip_recovery.recover_clip(client,{'grant':{'daily_budget':100}},
                    {'quality_policy':{'version':'58'},'segments':[{'subs':['correct']}]},0,
                    {'prompt':'Original','client_request_id':'run:store:0'},path,{},lambda:None,
                    lambda c,t,args,b:{**args,'max_credits':20},None,atomic,60,budget_limit=70)
            self.assertTrue(result.is_file())
            self.assertEqual(result,path)
            self.assertEqual(report['warning'],'RECOVERY_BUDGET_INSUFFICIENT')
            self.assertFalse(any(call.args[0]=='animate_image' for call in client.tool.call_args_list))

    def test_publication_reuses_only_hash_matched_policy(self):
        from publish.common.jobfile import quality_check_args
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            video=Path(directory)/'final.mp4';video.write_bytes(b'synthetic')
            proof=Path(str(video)+'.film.json')
            proof.write_text(json.dumps({'quality_policy_version':'58','machine_check':'pass',
                                         'sha256':hashlib.sha256(video.read_bytes()).hexdigest()}),encoding='utf-8')
            self.assertEqual(quality_check_args(video),['--quality-58'])
            video.write_bytes(b'changed')
            self.assertEqual(quality_check_args(video),[])

    def test_speech_runtime_repair_is_attempted_only_once(self):
        import speech_recovery
        with tempfile.TemporaryDirectory() as directory, \
             patch('render.speech_review.recognize',side_effect=RuntimeError('SPEECH_WORKER_CRASH')), \
             patch.object(speech_recovery.subprocess,'run',return_value=SimpleNamespace(returncode=1)) as repair:
            for _ in range(2):
                with self.assertRaisesRegex(RuntimeError,'SPEECH_CHECK_PENDING'):
                    speech_recovery.recognize(Path(directory)/'clip.mp4','small','zh',None)
            self.assertEqual(repair.call_count,1)

    def test_client_serializes_chinese_under_legacy_console_encoding(self):
        import os
        import subprocess
        import sys
        script = '''
import json,sys
from pathlib import Path
from automation_client import Client
class Response:
    headers={}
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,*args):return b'{"ok":true}'
class Opener:
    def open(self,request,**kwargs):
        Path(sys.argv[1]).write_bytes(request.data)
        return Response()
client=Client({'execution_token':'synthetic-test-only'})
client.opener=Opener()
client.post('/mcp',{'prompt':'\\u4f60\\u597d\\u4e16\\u754c'})
'''
        with tempfile.TemporaryDirectory() as directory:
            capture=Path(directory)/'capture.json'
            env={**os.environ,'PYTHONIOENCODING':'cp936','PYTHONUTF8':'0'}
            subprocess.run([sys.executable,'-c',script,str(capture)],env=env,check=True,capture_output=True)
            self.assertEqual(json.loads(capture.read_bytes().decode('utf-8'))['prompt'],'你好世界')


if __name__ == '__main__': unittest.main()
