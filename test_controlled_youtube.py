"""Retired publishing must never access a platform or install an OS task."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import automation
import toolkit


class PublisherTests(unittest.TestCase):
    def test_every_retired_platform_entry_returns_handoff(self):
        root=Path(__file__).parent/'publish'
        names={'upload','publish','auth','login','reschedule','yt_captions'}
        files=[p for p in root.glob('*/*.py') if p.parent.name!='common' and p.stem in names]
        self.assertEqual(len(files),18)
        with (patch('urllib.request.urlopen',side_effect=AssertionError('No platform API')),
              patch('webbrowser.open',side_effect=AssertionError('No browser login'))):
            for i,path in enumerate(files):
                spec=importlib.util.spec_from_file_location('retired_'+str(i),path)
                module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
                with contextlib.redirect_stdout(io.StringIO()):self.assertEqual(module.main(),2)

    def test_old_system_task_commands_do_not_generate_or_publish(self):
        for command in ('tick','tick-produce','tick-publish','install','install-daily-schedules','youtube-auth'):
            with (patch.object(sys,'argv',['automation.py',command]),patch.object(automation,'scheduled_store_day') as execute,
                  patch.object(automation.subprocess,'run') as run,contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(automation.main(),2);execute.assert_not_called();run.assert_not_called()

    def test_old_toolkit_install_and_youtube_commands_do_nothing(self):
        for arguments in (['install-schedule'],['enable-youtube'],['authorization','--install-schedules']):
            with (patch.object(sys,'argv',['toolkit.py',*arguments]),patch.object(toolkit.subprocess,'run') as run,
                  contextlib.redirect_stdout(io.StringIO())):
                self.assertEqual(toolkit.main(),2);run.assert_not_called()

    def test_assistant_schedule_contains_only_one_shot_production(self):
        grant={'status':'available','project_key':'shop','grant_no':'fixture','timezone':'Asia/Shanghai',
               'production_time':'10:00','publish_time':'19:00','auto_publish':True}
        with patch.object(automation,'authorization',return_value=grant),patch.object(automation.subprocess,'run') as run:
            result=automation.assistant_schedule()
        self.assertEqual([item['phase'] for item in result['tasks']],['produce'])
        self.assertEqual(result['tasks'][0]['argv'][-1],'produce-once')
        self.assertFalse(result['publication']['toolkit_publisher']);run.assert_not_called()

    def test_local_manifest_never_invokes_a_platform_script(self):
        from publish import dispatch
        value={'job':{},'artifacts':[]}
        with patch.object(dispatch,'snapshot',return_value=value),patch.object(dispatch,'film_review',return_value=None),patch.object(dispatch.subprocess,'run') as process:
            self.assertEqual(dispatch.dispatch(Path('fixture.json'),'youtube'),value)
            process.assert_not_called()
            with self.assertRaisesRegex(RuntimeError,'PUBLICATION_MOVED_TO_ASSISTANT_EGO'):
                dispatch.dispatch(Path('fixture.json'),'youtube',execute=True,confirmed=True)
            process.assert_not_called()

    def test_setup_has_no_browser_or_platform_dependency_install(self):
        source=(Path(__file__).parent/'bootstrap.py').read_text(encoding='utf-8')
        self.assertNotIn("run('chromium_install'",source)
        requirements=(Path(__file__).parent/'requirements.txt').read_text(encoding='utf-8')
        for package in ('google-api-python-client','google-auth','playwright'):
            self.assertNotIn(package,requirements)


if __name__ == '__main__':unittest.main()
