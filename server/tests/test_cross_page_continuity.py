import re
import unittest
from types import SimpleNamespace as NS

from utils.pdf_layout_repair import prepare_continued_inputs, redistribute_continued_outputs


def prepare(first, second, *, pages=(1, 2)):
    items = [{'id': 0, 'input': first, 'layout_label': 'plain text'},
             {'id': 1, 'input': second, 'layout_label': 'plain text'}]
    batch = NS(pages=[NS(page_number=n) for n in pages], paragraphs=[
        NS(layout_label='plain text', pdf_style=NS(font_size=10),
           box=NS(x=0, x2=250, y=0, y2=250)),
        NS(layout_label='plain text')])
    plans = prepare_continued_inputs(items, batch, [0, 1])
    return items, plans


class CrossPageContinuityTests(unittest.TestCase):
    def test_long_paragraph_only_sends_boundary_sentence_to_joined_item(self):
        prefix = '<style id="1">A complete, emphasized sentence about the model.</style> '
        prefix += 'A long explanation with a formula {v1} and Fig. 1. ' * 8
        items, plans = prepare(prefix + 'We performed',
                               'experiments on SFER datasets {v1} and DFER datasets {v2}. Later results.')
        self.assertEqual(len(plans), 1)
        self.assertEqual(items[0]['input'], prefix)
        self.assertTrue(items[1]['input'].startswith('We performed experiments'))
        self.assertEqual(items[2]['input'], ' Later results.')
        formulas = plans[0]['formulas']
        tokens = list(formulas)
        sentence = '我们在SFER数据集' + tokens[0] + '和DFER数据集' + tokens[1] + '上进行了实验。'
        results = {0: sentence, 1: '后续结果。', plans[0]['prefix_id']: '前面的模型介绍。'}
        redistribute_continued_outputs(results, plans)
        self.assertEqual(set(results), {0, 1})
        self.assertEqual(results[0] + results[1],
                         '前面的模型介绍。我们在SFER数据集{v1}和DFER数据集{v2}上进行了实验。后续结果。')
        self.assertNotIn('{v1}', results[0])
        self.assertNotIn('{v2}', results[0])

    def test_entire_second_fragment_can_be_one_sentence_without_empty_model_items(self):
        items, plans = prepare('Earlier work. We performed', 'experiments on the datasets.')
        self.assertEqual(len(plans), 1)
        self.assertTrue(all(item['input'].strip() for item in items))
        self.assertNotIn(1, [item['id'] for item in items])
        results = {0: '我们在数据集上进行了实验。', plans[0]['prefix_id']: '此前的研究。'}
        redistribute_continued_outputs(results, plans)
        self.assertEqual(results[0] + results[1], '此前的研究。我们在数据集上进行了实验。')

    def test_style_run_crossing_sentence_boundary_is_closed_and_reopened(self):
        items, plans = prepare('<style id="3">Previous sentence. We performed</style>',
                               '<style id="7">experiments on the datasets. Later findings.</style>')
        self.assertEqual(len(plans), 1)
        self.assertEqual(items[0]['input'], '<style id="3">Previous sentence. </style>')
        self.assertEqual(items[1]['input'], 'We performed experiments on the datasets.')
        self.assertEqual(items[2]['input'], '<style id="7"> Later findings.</style>')
        results = {0: '我们在数据集上进行了实验。', 1: '<style id="7">后续发现。</style>',
                   plans[0]['prefix_id']: '<style id="3">前句。</style>'}
        redistribute_continued_outputs(results, plans)
        self.assertTrue(results[0].startswith('<style id="3">前句。</style><style id="3">'))
        self.assertTrue(results[0].endswith('</style>'))
        self.assertTrue(results[1].startswith('<style id="7">'))
        self.assertNotIn('id="3"', results[1])
        self.assertNotIn('id="7"', results[0])

    def test_citation_tokens_are_unique_and_return_to_their_own_pages(self):
        items, plans = prepare('Earlier. Compared with {v1} we performed',
                               'experiments on {v1} and {v2}. Next.')
        self.assertEqual(len(plans), 1)
        formulas = list(plans[0]['formulas'])
        self.assertEqual(len(set(formulas)), 3)
        results = {0: formulas[0] + '对比实验在' + formulas[1] + '和' + formulas[2] + '上进行。',
                   1: '下一句。', plans[0]['prefix_id']: '前句。'}
        redistribute_continued_outputs(results, plans)
        self.assertEqual(results[0].count('{v1}'), 1)
        self.assertEqual(results[1].count('{v1}'), 1)
        self.assertEqual(results[1].count('{v2}'), 1)
        self.assertNotIn('{v2}', results[0])

    def test_missing_duplicate_or_reordered_formulas_reject_without_partial_changes(self):
        for mode in ['missing', 'duplicate', 'reordered']:
            with self.subTest(mode=mode):
                _, plans = prepare('We compared {v1} and performed', 'experiments on {v1}. Next.')
                first, second = plans[0]['formulas']
                sentence = {'missing': '我们进行了实验。',
                            'duplicate': first + first + '实验' + second,
                            'reordered': second + '实验' + first}[mode]
                results = {0: sentence, 1: '下一句。'}
                original = dict(results)
                with self.assertRaises(ValueError):
                    redistribute_continued_outputs(results, plans)
                self.assertEqual(results, original)

    def test_abbreviations_decimals_and_citation_periods_do_not_truncate_the_sentence(self):
        items, plans = prepare('Earlier sentence. Following Fig. 2 and Eq. 3 we performed',
                               'experiments with 3.14, e.g. a setup from Smith et al. on the datasets. Next.')
        self.assertEqual(len(plans), 1)
        joined = next(i for i in items if i['id'] == 0)['input']
        self.assertTrue(joined.startswith('Following Fig. 2 and Eq. 3'))
        self.assertTrue(joined.endswith('on the datasets.'))

    def test_unsupported_markup_and_mixed_boundary_styles_leave_inputs_intact(self):
        for first, second in [
            ('Earlier. We <style id="1">performed</style>', 'experiments. Next.'),
            ('Earlier. We performed', 'experiments <style id="1">on data</style>. Next.'),
            ('Earlier. We performed', 'experiments <broken>on data</broken>. Next.'),
            ('Earlier. We performed {name}', 'experiments. Next.'),
        ]:
            with self.subTest(first=first, second=second):
                items, plans = prepare(first, second)
                self.assertEqual(plans, [])
                self.assertEqual([i['input'] for i in items], [first, second])

    def test_same_page_and_missing_page_are_not_joined(self):
        for pages in [(1, 1), (1, 3)]:
            items, plans = prepare('Earlier. We performed', 'experiments. Next.', pages=pages)
            self.assertEqual(plans, [])

    def test_split_never_drops_whitespace_or_cuts_a_latin_word(self):
        _, plans = prepare('Earlier. We performed', 'experiments on datasets. Next.')
        sentence = 'We conducted experiments on datasets.'
        results = {0: sentence, 1: ' Next.', plans[0]['prefix_id']: 'Earlier. '}
        redistribute_continued_outputs(results, plans)
        self.assertEqual(results[0] + results[1], 'Earlier. ' + sentence + ' Next.')
        self.assertFalse(re.search(r'[A-Za-z]$', results[0]) and re.match(r'[A-Za-z]', results[1]))

    def test_source_glyph_width_limits_only_the_tail_in_a_large_paragraph(self):
        chars = [NS(char_unicode=c, box=NS(x=0, x2=5)) for c in 'Weperformed']
        pa = NS(layout_label='plain text', pdf_style=NS(font_size=10),
                box=NS(x=0, x2=250, y=0, y2=250),
                pdf_paragraph_composition=[NS(pdf_same_style_characters=NS(pdf_character=chars))])
        batch = NS(pages=[NS(page_number=1), NS(page_number=2)],
                   paragraphs=[pa, NS(layout_label='plain text')])
        items = [{'id': 0, 'input': 'Earlier. We performed'}, {'id': 1, 'input': 'experiments. Next.'}]
        plans = prepare_continued_inputs(items, batch, [0, 1])
        self.assertEqual(plans[0]['capacity'], 5.5)

    def test_short_joined_translation_leaves_text_in_both_original_slots(self):
        _, plans = prepare('We were', 'right.')
        results = {0: '我们是对的。'}
        redistribute_continued_outputs(results, plans)
        self.assertTrue(results[0])
        self.assertTrue(results[1])
        self.assertEqual(results[0] + results[1], '我们是对的。')

    def test_style_wrappers_never_enclose_citation_placeholders(self):
        _, plans = prepare('Earlier. We performed',
                           '<style id="7">experiments on data </style>{v1}<style id="7">. Later.</style>')
        self.assertEqual(len(plans), 1)
        token = next(iter(plans[0]['formulas']))
        results = {0: '我们在数据集' + token + '上进行了实验。',
                   1: '<style id="7">后续。</style>', plans[0]['prefix_id']: '前句。'}
        redistribute_continued_outputs(results, plans)
        self.assertIn('{v1}', results[1])
        self.assertNotRegex(results[1], r'<style[^>]*>[^<]*\{v1\}')

    def test_formula_hints_follow_the_remapped_tokens(self):
        batch = NS(pages=[NS(page_number=1), NS(page_number=2)], paragraphs=[
            NS(layout_label='plain text', box=NS(x=0,x2=250,y=0,y2=200)), NS(layout_label='plain text')])
        items = [{'id':0,'input':'Earlier {v1}. We performed','formula_placeholders_hint':{'{v1}':'first equation'}},
                 {'id':1,'input':'experiments on data {v1}. Next.', 'formula_placeholders_hint':{'{v1}':'[15]'}}]
        plans = prepare_continued_inputs(items,batch,[0,1])
        self.assertEqual(len(plans),1)
        self.assertEqual(items[0]['formula_placeholders_hint'],{'{v1}':'first equation'})
        self.assertEqual(items[1]['formula_placeholders_hint'],{'{v900000}':'[15]'})

    def test_natural_phrase_break_is_used_when_it_fits_the_page_budget(self):
        _, plans = prepare('Earlier. We performed',
                           'experiments on widely used datasets and compared with existing methods. Later.')
        results = {0:'我们在⟦PAGE_BREAK⟧广泛使用的数据集上进行了实验，并与现有方法进行了比较。',
                   1:'后续。', plans[0]['prefix_id']:'前句。'}
        redistribute_continued_outputs(results,plans)
        self.assertEqual(results[0],'前句。我们在')
        self.assertTrue(results[1].startswith('广泛使用的数据集'))
        self.assertNotIn('PAGE_BREAK', ''.join(results.values()))

    def test_oversized_or_misplaced_break_hint_is_removed_and_recomputed(self):
        for sentence in ['我们在广泛使用的数据集上进行了⟦PAGE_BREAK⟧实验。',
                         '我们在广泛使用的数据集上进行了实验。⟦PAGE_BREAK⟧']:
            _, plans = prepare('Earlier. We performed','experiments on widely used datasets. Later.')
            results={0:sentence,1:'后续。',plans[0]['prefix_id']:'前句。'}
            redistribute_continued_outputs(results,plans)
            self.assertEqual(results[0]+results[1], '前句。我们在广泛使用的数据集上进行了实验。后续。')


if __name__ == '__main__':
    unittest.main()
