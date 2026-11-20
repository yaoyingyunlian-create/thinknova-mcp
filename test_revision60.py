"""Revision 60 contract tests. No generation, publication or network calls."""
import copy
from pathlib import Path
import unittest
from automation import day_plan_request_version
from store_editorial import validate_dialogue_v3, short_reaction


def fixture(count=6):
    lines = [{'speaker':'customer' if i % 2 == 0 else 'staff',
              'listener':'staff' if i % 2 == 0 else 'customer', 'kind':'statement',
              'text':['今天想来看看花束呢','你想送给什么人呢','送给妈妈当生日礼物','那就挑妈妈喜欢的花','真的这束颜色很温柔','你拿起来看看合不合适','这些都是测试里的对白','那我就带这一束回家','卡片也能一起放进去吗'][i], 'action':'look at flowers','emotion':'curious',
              'classification':'好处或原因','source_ref':'F1','visual':'speaking mouth visible','camera':'medium'} for i in range(count)]
    segment = {'duration_seconds':15,'prompt':'People talking face to face','dialogue':lines,
               'subs':[line['text'] for line in lines],'scene_life':'A used workbench','first_frame_prompt':'Staff arranging flowers'}
    return {'film_purpose':'service','shop_name':'虚构测试店','featured_service':'花束',
            'script_rules_revision':'60','dialogue_rules_revision':'2.4',
            'script':{'template':'two_person_dialogue','voice_identity':'fixed staff'},
            'customer_identity':'fictional shopper','closing_overlay':['虚构测试店'],
            'segments':[segment], 'week_rows':[{'format':'shop_visit'}],
            'script_sources':{'F1':'提供花束服务'},'category_direction':'花束',
            'content_angle':{'id':'flowers','source_ref':'F1'},
            'dialogue_classification_counts':{'麻烦':0,'原话':0,'情境':0,'好处或原因':count}}


class Revision60Tests(unittest.TestCase):
    def test_negotiation_retains_old_server_contract(self):
        self.assertEqual(day_plan_request_version({'day_plan_request_version':8}),8)
        self.assertEqual(day_plan_request_version({'day_plan_request_version':8,'supported_day_plan_request_versions':[8,9]}),9)

    def test_new_and_old_line_counts_are_distinct(self):
        for count in (5,8): validate_dialogue_v3(fixture(count))
        for count in (4,9):
            with self.assertRaisesRegex(ValueError,'LINES_INVALID'):validate_dialogue_v3(fixture(count))
        old=fixture(6);old['script_rules_revision']='59'
        with self.assertRaisesRegex(ValueError,'LINES_INVALID'):validate_dialogue_v3(old)
        old=fixture(3);old['script_rules_revision']='59';validate_dialogue_v3(old)

    def test_reactions_remain_in_captions_and_total_lines(self):
        plan=fixture();line=plan['segments'][0]['dialogue'][1]
        line.update(text='泡的？',classification='情境',source_ref='')
        plan['segments'][0]['subs'][1]='泡的？'
        plan['dialogue_classification_counts']['好处或原因']-=1
        validate_dialogue_v3(plan)
        self.assertTrue(short_reaction('真的？'));self.assertFalse(short_reaction('很便宜'))
        changed=copy.deepcopy(plan);changed['segments'][0]['subs'].pop(1)
        with self.assertRaisesRegex(ValueError,'CAPTIONS_MISMATCH'):validate_dialogue_v3(changed)

    def test_text_and_address_contract(self):
        text=(Path(__file__).parent/'rules/store-film-rules-v60.md').read_text(encoding='utf-8')
        self.assertLessEqual(len(text),4000)
        for term in ['门店类结尾直接说地址','段2 第一句接段1 最后一句','没有门店照片时']:
            self.assertIn(term,text)
        self.assertTrue((Path(__file__).parent/'rules/store-film-rules-v59.md').is_file())


if __name__ == '__main__':unittest.main()
