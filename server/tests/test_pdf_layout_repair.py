import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

from utils.pdf_layout_repair import deduplicate_text_layouts, normalize_drop_cap_words, prepare_continued_inputs, redistribute_continued_outputs, center_translated_title, annotate_title_terms
from utils.install_layout_repair import install_layout_repair


def layout(i, x, y, x2, y2, label='plain text', conf=0.5):
    return NS(id=i, box=NS(x=x, y=y, x2=x2, y2=y2), class_name=label, conf=conf)


def drop_cap_page():
    chars = []
    for i, letter in enumerate('FACIAL expressions'):
        chars.append(NS(char_unicode=letter, pdf_style=NS(font_size=29.4 if i == 0 else 9.96, font_id='bold' if i < 6 else 'body'),
                        box=NS(x=312 + i * 7, y=285 if i == 0 else 298), vertical=False, formula_layout_id=None))
    para = NS(layout_label='plain text', box=NS(x=312), pdf_paragraph_composition=[NS(pdf_line=NS(pdf_character=chars))])
    return NS(pdf_paragraph=[para]), chars


class LayoutRepairTest(unittest.TestCase):
    def test_numeric_tick_runs_are_protected_without_excluding_prose(self):
        from utils.pdf_layout_repair import is_numeric_label
        for text in ['20','50 80','−0.25','10% 20%','1,000','50～80']:
            self.assertTrue(is_numeric_label(NS(unicode=text)),text)
        for text in ['Number of parameters (M)','2026年','1. Introduction','R(2+1)D-18','',None]:
            self.assertFalse(is_numeric_label(NS(unicode=text)),text)

    def test_real_overlapping_page_tail_detections_keep_full_line(self):
        page = NS(page_layout=[layout(17,319,41,564,55,conf=.421), layout(19,351,42,539,55,conf=.274),
                               layout(16,310,55,564,164,conf=.689), layout(18,310,55,564,164,conf=.349)])
        deduplicate_text_layouts(page)
        self.assertEqual([l.id for l in page.page_layout], [17,16])

    def test_adjacent_columns_formulas_and_small_line_inside_tall_paragraph_survive(self):
        page = NS(page_layout=[layout(1,0,0,250,300),layout(2,260,0,510,300),
                               layout(3,20,20,200,30),layout(4,20,20,200,30,'formula'),
                               layout(5,20,35,200,45)])
        deduplicate_text_layouts(page)
        self.assertEqual(len(page.page_layout), 5)

    def test_drop_cap_word_becomes_contiguous_prose_before_formula_detection(self):
        page, chars = drop_cap_page()
        normalize_drop_cap_words(page)
        self.assertTrue(all(c.pdf_style.font_size == 9.96 and c.pdf_style.font_id == 'body' for c in chars[:6]))
        self.assertEqual(''.join(c.char_unicode for c in chars), 'FACIAL expressions')

    def test_explicit_formula_and_regular_initial_are_not_normalized(self):
        for mode in ['formula', 'regular', 'not_prose']:
            page, chars = drop_cap_page()
            if mode == 'formula':
                chars[1].formula_layout_id = 7
            elif mode == 'regular':
                chars[0].pdf_style.font_size = 9.96
            else:
                page.pdf_paragraph[0].layout_label = 'isolate_formula'
            normalize_drop_cap_words(page)
            self.assertEqual(chars[0].pdf_style.font_id, 'bold')

    def test_small_caps_at_eighty_percent_are_prose_and_keep_a_normal_baseline(self):
        page, chars = drop_cap_page()
        page.pdf_paragraph[0].unicode = 'F ACIAL expressions'
        for c in chars[1:6]:
            c.pdf_style.font_size = 9.96 * 0.8
        normalize_drop_cap_words(page)
        self.assertTrue(all(c.pdf_style.font_size == 9.96 for c in chars[:6]))
        self.assertTrue(all(c.box.y == chars[7].box.y for c in chars[:6]))
        self.assertAlmostEqual(chars[0].box.y2 - chars[0].box.y, 9.96)
        self.assertEqual(page.pdf_paragraph[0].unicode, 'FACIAL expressions')
        self.assertEqual(chars[0].box.x2, chars[1].box.x)

    def test_two_letter_drop_cap_word_is_normalized_without_a_word_dictionary(self):
        page, chars = drop_cap_page()
        chars[:] = [chars[0], chars[1], *chars[6:]]
        chars[0].char_unicode, chars[1].char_unicode = 'I', 'N'
        normalize_drop_cap_words(page)
        self.assertEqual(chars[0].pdf_style.font_size, 9.96)
        self.assertEqual(''.join(c.char_unicode for c in chars), 'IN expressions')

    def test_raised_initial_and_lowered_suffix_are_not_drop_caps(self):
        for mode in ['raised', 'suffix']:
            page, chars = drop_cap_page()
            if mode == 'raised':
                chars[0].box.y = 310
            else:
                chars[1].box.y = 280
            normalize_drop_cap_words(page)
            self.assertEqual(chars[0].pdf_style.font_id, 'bold')

    def test_install_is_idempotent_and_preserves_preexisting_engine_edits(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)/'Lib/site-packages/babeldoc/format/pdf/document_il/midend'
            folder.mkdir(parents=True)
            (folder.parent/'backend').mkdir()
            (folder.parent/'backend/pdf_creater.py').write_text('class Writer:\n    def write(self):\n        pdf.subset_fonts(fallback=False)\n        if True:\n            gc_level = 1\n',encoding='utf8')
            original = 'class Engine:\n    def process_page(self, page: Page):\n        existing_custom_fix(page)\n'
            for name in ['paragraph_finder.py','styles_and_formulas.py']:
                (folder/name).write_text(original, encoding='utf8')
            (folder/'typesetting.py').write_text('class Engine:\n    def render(self):\n        for paragraph in paragraphs:\n            self.render_paragraph(paragraph, page, fonts)\n', encoding='utf8')
            numeric_import = 'from babeldoc.format.pdf.document_il.utils.paragraph_helper import (\n    is_pure_numeric_paragraph,\n)\n'
            (folder/'il_translator.py').write_text(numeric_import+'class Engine:\n    def get_translate_input(self):\n        placeholder_id = 1\n        for composition in compositions:\n            if len(placeholders) > 40 and not disable_rich_text_translate:\n                return None\n    def pre_translate(self):\n        if paragraph.vertical:\n            return None, None\n        translate_input = self.get_translate_input(\n            paragraph, page_font_map, disable_rich_text_translate\n        )\n',encoding='utf8')
            (folder.parent.parent/'high_level.py').write_text('def translate():\n    support_llm_term_extraction = translator_supports_llm(term_extraction_engine)\n',encoding='utf8')
            vision=folder.parents[3]/'docvision'
            vision.mkdir()
            (vision/'doclayout.py').write_text('import pymupdf\nclass OnnxModel:\n    def __init__(self):\n        self.model = onnxruntime.InferenceSession(\n            model,\n            providers=providers,\n        )\n    def predict(self, image, imgsz=800, batch_size=16, **kwargs):\n        return []\n',encoding='utf8')
            (folder/'automatic_term_extractor.py').write_text('class Terms:\n    def clean(self, llm_output):\n        return llm_output.strip()\n',encoding='utf8')
            (folder/'il_translator_llm_only.py').write_text(numeric_import+'PROMPT = """- Produce fluent, professional $lang_out.\n"""\nclass Engine:\n    def translate(self):\n        if True:\n            json_format_input_str = json.dumps(\n                items)\n            if len(translation_results) != len(inputs):\n                raise ValueError()\n', encoding='utf8')
            self.assertTrue(install_layout_repair(temp))
            self.assertFalse(install_layout_repair(temp))
            self.assertIn('existing_custom_fix(page)', (folder/'paragraph_finder.py').read_text())
            self.assertEqual((folder/'paragraph_finder.py.before_zotero_layout_repair').read_text(), original)
            self.assertIn('preserve_reference_paragraphs(docs, translation_config)', (folder.parent.parent/'high_level.py').read_text())
            self.assertTrue((Path(temp)/'Lib/site-packages/zotero_pdf_reference_filter.py').exists())
            self.assertTrue((Path(temp)/'Lib/site-packages/zotero_pdf_author_filter.py').exists())
            self.assertEqual((folder/'styles_and_formulas.py').read_text().count('prepare_author_paragraphs(page,'),1)
            self.assertIn('_zotero_author_paragraph_ids', (folder/'il_translator.py').read_text())
            self.assertIn('@cached_layout_predict', (vision/'doclayout.py').read_text())

    def test_only_unfinished_body_sentence_on_adjacent_pages_is_linked(self):
        for first, second, label, linked in [
            ('How to reduce the negative impact of data deficiencies', 'and ambiguous annotations remains a challenge.', 'plain text', True),
            ('This sentence is complete.', 'another paragraph', 'plain text', False),
            ('A section', 'another section', 'title', False),
            ('Some prose', 'A new sentence', 'plain text', False),
        ]:
            items = [{'id':0,'input':first}, {'id':1,'input':f"<style id='1'>{second}</style>Later sentence."}]
            batch = NS(pages=[NS(page_number=0), NS(page_number=1)], paragraphs=[NS(unicode=first,layout_label=label,box=NS(x=0,x2=240,y=0,y2=12)), NS(unicode=second,layout_label=label)])
            plans = prepare_continued_inputs(items, batch, [0,1])
            self.assertEqual(bool(plans), linked)
            if linked:
                self.assertEqual(items[0]['input'], first+' '+second)
                self.assertEqual(items[1]['input'], 'Later sentence.')

    def test_joined_translation_is_preserved_exactly_across_two_output_slots(self):
        sentence = '如何减轻数据不足与标注歧义带来的负面影响，仍是DFER面临的一项挑战。'
        results = {0: sentence, 1: '后续段落。'}
        redistribute_continued_outputs(results, [{'first':0,'second':1,'opening':"<style id='1'>",'closing':'</style>','capacity':24}])
        tail = results[1].split('</style>')[0].split('>')[1]
        self.assertEqual(results[0] + tail, sentence)
        self.assertLessEqual(len(results[0]), 24)
        self.assertTrue(results[1].endswith('后续段落。'))

    def test_formula_continuation_is_left_to_upstream(self):
        items = [{'id':0,'input':'The equation {v1}'},{'id':1,'input':'and another term. Next sentence.'}]
        before = [dict(i) for i in items]
        batch = NS(pages=[NS(page_number=0), NS(page_number=1)], paragraphs=[NS(unicode='The equation x',layout_label='plain text'),NS(unicode='and another term.',layout_label='plain text')])
        self.assertEqual(prepare_continued_inputs(items,batch,[0,1]), [])
        self.assertEqual(items, before)

    def test_translated_title_lines_share_center(self):
        chars = []
        for x,y in [(10,80),(20,80),(10,60)]:
            box = NS(x=x, y=y, x2=x+10, y2=y+10)
            chars.append(NS(box=box, visual_bbox=NS(box=box) if y == 80 else None))
        para = NS(unicode='中文标题', box=NS(x=0,x2=100),
                  pdf_paragraph_composition=[NS(pdf_character=c) for c in chars])
        center_translated_title(para, NS(_zotero_centered_titles={id(para)}))
        self.assertEqual((chars[0].box.x+chars[1].box.x2)/2,50)
        self.assertEqual((chars[2].box.x+chars[2].box.x2)/2,50)

    def test_facial_landmark_hint_is_scoped_to_matching_title(self):
        items = [{'id':0,'input':'Adapting Landmark-Aware Models for Facial Expression Recognition','layout_label':'title'},
                 {'id':1,'input':'Historic landmarks of a city','layout_label':'title'},
                 {'id':2,'input':'Facial landmarks','layout_label':'plain text'}]
        annotate_title_terms(items)
        self.assertIn('面部关键点',items[0]['translation_hint'])
        self.assertIn('面向Y的X适配',items[0]['translation_hint'])
        self.assertNotIn('translation_hint',items[1])
        self.assertNotIn('translation_hint',items[2])


if __name__ == '__main__':
    unittest.main()
