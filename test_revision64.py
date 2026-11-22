from copy import deepcopy
from difflib import SequenceMatcher
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as Row
from unittest.mock import patch

from automation import preflight_store_script
from render import assemble
from store_film import missing_product_facts, repeated_dialogue_lines


class Revision64Tests(unittest.TestCase):
    def test_only_confirmed_distinct_benefits_count(self):
        shop = {'featured_service': '暖机', 'viewer_action': '私信暖机',
                'confirmed_facts': {'methods_and_reasons': ['暖机', '一键排水', '一键排水。'],
                                    'visible_details': ['面板显示余量'],
                                    'customer_situations': ['早班来不及']}}
        self.assertEqual(missing_product_facts(shop), ['shop_profile.confirmed_facts'])
        shop['confirmed_facts']['visible_details'].append('可拆洗滤网')
        self.assertEqual(missing_product_facts(shop), [])

    def test_repetition_and_inflight_compatibility(self):
        self.assertEqual(repeated_dialogue_lines(['先看滤网。', '滤网可以拆洗。', '拆洗用温水。']), [2, 3])
        self.assertEqual(repeated_dialogue_lines(['Open the cover.', 'Cover has a clip.', 'Clip locks here.']), [2, 3])
        with tempfile.TemporaryDirectory() as folder:
            preflight_store_script({'script_rules_revision': '64'}, {}, Path(folder), {'task_0': 'existing'})
            with patch('automation.shutil.which') as codex:
                with self.assertRaisesRegex(RuntimeError, 'DAY_PLAN_PRODUCT_FACTS_REQUIRED'):
                    preflight_store_script({'script_rules_revision': '64'}, {'effective_rules': {}}, Path(folder), {})
                codex.assert_not_called()

    def test_review_timeout_holds_the_script(self):
        import subprocess
        shop = {'featured_service': '暖机', 'viewer_action': '私信暖机',
                'confirmed_facts': {'visible_details': ['一键排水', '显示余量', '可拆洗']}}
        plan = {'script_rules_revision': '64', 'segments': [{'dialogue': [{'text': '暖机能做什么？'}]}]}
        with tempfile.TemporaryDirectory() as folder, patch('store_editorial.validate_dialogue_v3'), \
             patch('automation.shutil.which', return_value='codex'), \
             patch('automation.subprocess.run', side_effect=subprocess.TimeoutExpired('codex', 120)):
            with self.assertRaisesRegex(RuntimeError, 'DAY_PLAN_BLIND_REVIEW_UNAVAILABLE'):
                preflight_store_script(plan, {'effective_rules': {'shop_profile': shop}}, Path(folder), {})

    def test_repair_edits_only_marked_line_and_is_replayed_on_resume(self):
        lines = ['我是店员。', '这台机器好洗吗？', '滤网可以拆洗。', '要试用就私信。']
        original = {'script_rules_revision': '64', 'segments': [
            {'dialogue': [{'text': line} for line in lines], 'subs': lines[:]}]}
        shop = {'featured_service': '暖机', 'viewer_action': '私信暖机',
                'confirmed_facts': {'visible_details': ['一键排水', '显示余量', '可拆洗']}}
        amended = ['我是店员，给你看暖机。', *lines[1:]]
        plan = deepcopy(original)
        with tempfile.TemporaryDirectory() as folder, patch('store_editorial.validate_dialogue_v3'), \
             patch('automation.inspect_store_dialogue', side_effect=[[{'line': 1, 'reason': 'MISSING_PRODUCT'}], []]) as review, \
             patch('automation.codex_dialogue_json', return_value={'lines': amended}) as rewrite:
            directory = Path(folder)
            preflight_store_script(plan, {'effective_rules': {'shop_profile': shop}}, directory, {})
            restored = deepcopy(original)
            preflight_store_script(restored, {}, directory, {'task_0': 'existing'})
            self.assertEqual(plan, restored)
            self.assertEqual(plan['segments'][0]['subs'], amended)
            self.assertEqual(review.call_count, 2)
            rewrite.assert_called_once()

    def test_script_punctuation_and_one_timed_cue_per_line(self):
        lines = ['五台，都能用？', '地址在滨海路十二号靠北门。']
        spoken = [Row(words=[Row(word='舞台都能用', start=1, end=2), Row(word='地址在滨海路十二号靠北门', start=3, end=5)])]
        with patch('speech_review.caption_match', side_effect=lambda a, b: SequenceMatcher(None, a, b)):
            cues = assemble.align_captions(lines, spoken, 0)
        self.assertEqual([cue['text'] for cue in cues], lines)
        self.assertLess(cues[0]['end'], cues[1]['start'])
        with tempfile.TemporaryDirectory() as folder:
            ass = Path(folder) / 'captions.ass'
            assemble.write_ass(ass, {'script_rules_revision': '64', 'film_profile': 'store_v2'}, cues, None, 'Microsoft YaHei')
            rendered = ass.read_text(encoding='utf-8')
            self.assertIn('Sub,Microsoft YaHei,87,', rendered)
            self.assertIn(',1,13,0,2,60,60,400,', rendered)
            self.assertEqual(rendered.count('Dialogue: 0,'), 2)
            self.assertIn(r'\N', rendered)
