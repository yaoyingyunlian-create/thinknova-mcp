"""Retired publishing must never access a platform or install an OS task."""
import contextlib
import importlib.util
import io
import json
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

    def test_assistant_setup_uses_existing_mcp_without_pairing(self):
        for command in ('assistant-schedule', 'enable-production'):
            with (patch.object(sys, 'argv', ['toolkit.py', command]),
                  patch.object(automation, 'authorization') as authorize,
                  patch('urllib.request.build_opener') as network,
                  patch('webbrowser.open') as browser,
                  contextlib.redirect_stdout(io.StringIO()) as output):
                self.assertEqual(toolkit.main(), 0)
                authorize.assert_not_called()
                network.assert_not_called()
                browser.assert_not_called()
            result = json.loads(output.getvalue())
            self.assertEqual(result['status'], 'assistant_workflow')
            self.assertEqual(result['production']['connection'], 'existing_thinknova_mcp_oauth')
            self.assertFalse(result['production']['device_pairing_required'])
            self.assertFalse(result['publication']['toolkit_publisher'])

    def test_unpaired_old_timer_points_to_mcp_without_attempting_setup(self):
        with (patch.object(sys, 'argv', ['automation.py', 'produce-once']),
              patch.object(automation.platform, 'system', return_value='Windows'),
              patch.object(automation, 'CREDENTIALS') as credentials,
              patch.object(automation, 'scheduled_store_day') as execute,
              contextlib.redirect_stdout(io.StringIO()) as output):
            credentials.is_file.return_value = False
            self.assertEqual(automation.main(), 2)
            execute.assert_not_called()
        self.assertEqual(json.loads(output.getvalue())['reason_code'], 'USE_EXISTING_MCP_CONNECTION')

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
