"""Isolated staged-toolkit regressions; synthetic media only, never publish."""
import base64
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import health
import bootstrap
import secure_state
import automation
import monitoring

spec=importlib.util.spec_from_file_location('assemble',Path(__file__).parent/'render/assemble.py')
assemble=importlib.util.module_from_spec(spec);spec.loader.exec_module(assemble)
spec=importlib.util.spec_from_file_location('dispatch',Path(__file__).parent/'publish/dispatch.py')
dispatch=importlib.util.module_from_spec(spec);spec.loader.exec_module(dispatch)

class Contracts(unittest.TestCase):
    def test_core_does_not_require_browser(self):
        checks=[{'name':n,'status':'pass'} for n in ('python','files','virtual_environment','git','ffmpeg','ffprobe','libass','cjk_font')]
        checks += [{'name':'chromium_runtime','status':'fail'},{'name':'ego_runtime','status':'fail'}]
        states=health.capabilities(checks)
        self.assertEqual(states['core_production'],'pass');self.assertEqual(states['browser_publishing'],'fail');self.assertEqual(states['automation'],'unknown')

    def test_bad_jobs_are_explicit_errors(self):
        for job in ({'out':'a.mp4','clips':['bad']},{'out':'a.mp4','clips':[{'file':'a','dur':float('nan')}]},{'out':'a.mp4','clips':[{'file':'a','start':-1}]},{'out':'a.mp4','clips':[{'file':'a','fit':'stretch'}]}):
            with self.assertRaises(assemble.Stop):assemble.validate_job(job)

    def test_mac_without_brew_has_one_official_action(self):
        with patch.object(bootstrap.platform,'system',return_value='Darwin'),patch.object(bootstrap.shutil,'which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'https://brew.sh'):bootstrap.install_missing('ffmpeg')

    def test_mac_keychain_no_plaintext_secret_in_file_or_argv(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'test.keychain';secret={'telemetry_token':'synthetic-secret'}
            encoded=base64.b64encode(json.dumps(secret,ensure_ascii=False).encode('utf-8'))
            replies=[subprocess.CompletedProcess([],0),subprocess.CompletedProcess([],0,encoded),subprocess.CompletedProcess([],0,encoded)]
            with patch.object(secure_state.platform,'system',return_value='Darwin'),patch.object(secure_state.subprocess,'run',side_effect=replies) as run:
                secure_state.save(path,secret);self.assertEqual(secure_state.load(path),secret)
                self.assertNotIn(b'synthetic-secret',path.read_bytes())
                for call in run.call_args_list:self.assertNotIn('synthetic-secret',str(call.args))

    def test_duplicate_scope_and_unknown_outcomes(self):
        candidate={'platform':'youtube','target_account':'channel','title':'A','caption':'B','artifacts':[{'sha256':'abc'}]}
        history=[{**candidate,'state':'outcome_unknown','attempted_at':datetime.now(timezone.utc).isoformat()}]
        self.assertTrue(dispatch.duplicate(candidate,history))
        self.assertFalse(dispatch.duplicate({**candidate,'platform':'tiktok'},history))
        self.assertFalse(dispatch.duplicate({**candidate,'target_account':'other'},history))

    def test_platform_copy_must_be_distinct(self):
        with self.assertRaisesRegex(RuntimeError,'PLATFORM_COPY_VARIATION_REQUIRED'):
            dispatch.validate_variants({'title':'A','caption':'B','platforms':{'youtube':{},'tiktok':{}}})
        dispatch.validate_variants({'platforms':{'youtube':{'title':'A'},'tiktok':{'title':'B'}}})

    def test_mac_launchagent_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'task.plist'
            with patch.object(automation.platform,'system',return_value='Darwin'),patch.object(automation,'schedule_path',return_value=path),patch.object(automation.os,'getuid',create=True,return_value=501),patch.object(automation.subprocess,'run') as run:
                automation.install_runner()
                import plistlib
                value=plistlib.loads(path.read_bytes())
                self.assertEqual(value['ProgramArguments'][-1],'tick')
                self.assertEqual(value['StartInterval'],300)
                self.assertFalse(any('token' in str(v).lower() for v in value['ProgramArguments']))
                self.assertEqual(run.call_args.args[0][0:2],['launchctl','bootstrap'])

    def test_recovering_one_platform_keeps_other_faults(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            with patch.object(monitoring,'STATE',root),patch.object(monitoring,'TOKEN',root/'absent.dpapi'):
                monitoring.event('youtube','publication','AUTH_REQUIRED')
                monitoring.event('tiktok','publication','LOGIN_EXPIRED')
                monitoring.event('youtube','publication',None)
                pending=json.loads((root/'monitor_pending.json').read_text(encoding='utf-8'))
                self.assertEqual(list(pending),['tiktok:publication'])

    def test_oauth_client_rejects_custom_token_endpoint(self):
        yt_spec=importlib.util.spec_from_file_location('staged_yt_common',Path(__file__).parent/'publish/youtube/yt_common.py')
        yt_common=importlib.util.module_from_spec(yt_spec);yt_spec.loader.exec_module(yt_common)
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'client.json'
            value={'installed':{'client_id':'synthetic.apps.googleusercontent.com','auth_uri':'https://accounts.google.com/o/oauth2/auth','token_uri':'https://oauth2.googleapis.com/token'}}
            path.write_text(json.dumps(value),encoding='utf-8')
            with patch.object(yt_common,'CLIENT',str(path)):
                self.assertEqual(yt_common._client_config(),value)
                value['installed']['token_uri']='https://example.invalid/steal'
                path.write_text(json.dumps(value),encoding='utf-8')
                with self.assertRaisesRegex(SystemExit,'YOUTUBE_COMPANY_CLIENT_INVALID'):yt_common._client_config()

    def test_codex_only_consumes_plan_not_shell(self):
        with self.assertRaises(RuntimeError):automation.validate_plan({'title':'A','description':'B','shots':[{'prompt':'test'}],'command':'publish'})

@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'Media tools unavailable')
class Media(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='thinknova-stage-media-');cls.root=Path(cls.temp.name)
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc2=s=160x284:r=30:d=0.4','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=0.4','-shortest','-c:v','libx264','-c:a','aac',str(cls.root/'中文 空格.mp4')],check=True,capture_output=True)
        cls.script=Path(__file__).parent/'render/assemble.py'
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def run_job(self,name,clip,*extra):
        path=self.root/(name+'.json');path.write_text(json.dumps({'out':name+'.mp4','clips':[clip]},ensure_ascii=False),encoding='utf-8')
        result=subprocess.run([sys.executable,str(self.script),str(path),'--json',*extra],capture_output=True,text=True,encoding='utf-8',timeout=90)
        return result,json.loads(result.stdout)
    def test_subsecond_contact_sheet_and_chinese_paths(self):
        sentinel=self.root/'_frames';sentinel.mkdir(exist_ok=True);(sentinel/'keep.txt').write_text('customer',encoding='utf-8')
        result,report=self.run_job('caption',{'file':'中文 空格.mp4','text':'中文测试'})
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue((self.root/'caption_sheet.jpg').is_file())
        self.assertEqual(report['visual_review'],'pending');self.assertTrue((sentinel/'keep.txt').exists())
        again,report=self.run_job('caption',{'file':'中文 空格.mp4'})
        self.assertEqual(again.returncode,1);self.assertIn('OUTPUT_EXISTS',report['error'])
    def test_silent_video_is_valid(self):
        result,report=self.run_job('silent',{'file':'中文 空格.mp4','audio':'mute'})
        self.assertEqual(result.returncode,0,result.stderr);self.assertEqual(report['machine_check'],'pass')
    def test_freeze_padding_rejected(self):
        result,report=self.run_job('short',{'file':'中文 空格.mp4','dur':2})
        self.assertEqual(result.returncode,1);self.assertIn('SHOT_TOO_SHORT',report['error']);self.assertFalse((self.root/'short.mp4').exists())

if __name__=='__main__':unittest.main()
