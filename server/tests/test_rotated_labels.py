import unittest
import unicodedata
import tempfile
from pathlib import Path
from types import SimpleNamespace as NS
import pymupdf as fitz

from utils.rotated_labels import (
    collect_rotated_labels, draw_rotated_label, collect_oblique_labels,
    restore_oblique_labels, repair_rotated_labels,
)
from utils.pdf_layout_repair import deduplicate_text_layouts


class FigureLabelTests(unittest.TestCase):
    def test_oblique_source_font_geometry_color_and_background_survive(self):
        source, target = fitz.open(), fitz.open()
        src = source.new_page(width=300, height=300)
        out = target.new_page(width=300, height=300)
        for page in (src, out):
            page.draw_rect(page.rect, color=None, fill=(.1, .3, .8))
        for angle, origin, text in [(45, (60, 80), 'NE'), (-30, (150, 90), 'HA'),
                                    (135, (150, 180), 'SU')]:
            point = fitz.Point(origin)
            src.insert_text(point, text, fontname='tiro', fontsize=12,
                            morph=(point, fitz.Matrix(angle)), color=(1, 1, 1))
        src.insert_text((30, 250), 'Source caption')
        out.insert_text((30, 250), 'Target caption')
        reports = restore_oblique_labels(out, src)
        self.assertEqual(len(reports), 3)
        self.assertEqual(restore_oblique_labels(out, source[0]), [])
        self.assertNotIn('Source caption', out.get_text())
        self.assertIn('Target caption', out.get_text())
        # Glyph outlines, colors and exact positions matter as well as text.
        rect = fitz.Rect(20, 20, 220, 210)
        self.assertEqual(source[0].get_pixmap(clip=rect, matrix=fitz.Matrix(3, 3)).samples,
                         out.get_pixmap(clip=rect, matrix=fitz.Matrix(3, 3)).samples)

    def test_type3_custom_codes_survive_font_subset_save_and_reopen(self):
        source, target = fitz.open(), fitz.open()
        src = source.new_page(width=200, height=200)
        def obj(value, stream=None):
            xref = source.get_new_xref()
            source.update_object(xref, value)
            if stream is not None:
                source.update_stream(xref, stream)
            return xref
        # Original vector glyphs, with PDF codes 1 and 2 instead of ASCII.
        n = obj('<< >>', b'600 0 0 0 600 700 d1 0 0 100 700 re f 500 0 100 700 re f')
        e = obj('<< >>', b'600 0 0 0 600 700 d1 0 0 100 700 re f 0 600 600 100 re f')
        font = obj(f'<< /Type /Font /Subtype /Type3 /BaseFont /TestLabels /Name /TestLabels '
                   f'/FontBBox [0 0 600 700] /FontMatrix [.001 0 0 .001 0 0] '
                   f'/CharProcs << /N {n} 0 R /E {e} 0 R >> '
                   f'/Encoding << /Differences [1 /N /E] >> /FirstChar 1 /LastChar 2 '
                   f'/Widths [600 600] /Resources << >> >>')
        source.xref_set_key(src.xref, 'Resources', f'<< /Font << /F1 {font} 0 R >> >>')
        src.set_contents(obj('<< >>', b'BT /F1 12 Tf .70710678 .70710678 -.70710678 .70710678 80 100 Tm <0102> Tj ET'))
        out = target.new_page(width=200, height=200)
        report = restore_oblique_labels(out, src)
        self.assertEqual([r['source'] for r in report], ['NE'])
        self.assertEqual(''.join(out.get_text().split()), 'NE')
        target.subset_fonts()
        reopened = fitz.open(stream=target.tobytes(), filetype='pdf')
        self.assertEqual(''.join(reopened[0].get_text().split()), 'NE')
        self.assertEqual(source[0].get_pixmap(matrix=fitz.Matrix(4, 4)).samples,
                         reopened[0].get_pixmap(matrix=fitz.Matrix(4, 4)).samples)

    def test_only_missing_glyphs_are_restored(self):
        source, target = fitz.open(), fitz.open()
        src, out = source.new_page(), target.new_page()
        point = fitz.Point(80, 100)
        for page, text in [(src, 'NE'), (out, 'N')]:
            page.insert_text(point, text, fontsize=12, morph=(point, fitz.Matrix(45)))
        report = restore_oblique_labels(out, src)
        self.assertEqual(sum(r['glyphs'] for r in report), 1)
        self.assertEqual(sorted(c[0] for s in out.get_texttrace() for c in s['chars']),
                         [ord('E'), ord('N')])

    def test_oblique_cid_font_encoding_is_preserved(self):
        source, target = fitz.open(), fitz.open()
        src, out = source.new_page(), target.new_page()
        point = fitz.Point(80, 100)
        src.insert_text(point, '快乐', fontname='china-s', fontsize=12,
                        morph=(point, fitz.Matrix(45)))
        restore_oblique_labels(out, src)
        self.assertIn('快乐', out.get_text())
        self.assertEqual(source[0].get_pixmap().samples, out.get_pixmap().samples)

    def test_horizontal_vertical_and_url_text_are_excluded(self):
        source = fitz.open()
        src = source.new_page()
        src.insert_text((40, 40), 'NE')
        src.insert_text((80, 80), 'NE', rotate=90)
        point = fitz.Point(100, 200)
        src.insert_text(point, 'https://example.org', morph=(point, fitz.Matrix(45)))
        self.assertEqual(collect_oblique_labels(src), [])

    def test_selected_page_hook_preserves_codes_without_translation_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'source.pdf'
            source, target = fitz.open(), fitz.open()
            for _ in range(2):
                src = source.new_page()
                point = fitz.Point(80, 100)
                src.insert_text(point, 'NE', morph=(point, fitz.Matrix(45)))
                target.new_page()
            source.save(path)
            source.close()
            def translate(text):
                self.fail('Oblique source codes must not be sent to the translator')
            config = NS(input_file=str(path), skip_translation=False,
                        only_parse_generate_pdf=False, should_translate_page=lambda n: n == 2,
                        raise_if_cancelled=lambda: None, translator=NS(translate=translate))
            document = NS(page=[NS(page_number=0), NS(page_number=1)])
            report = repair_rotated_labels(target, config, document)
            self.assertEqual([r['page'] for r in report], [2])
            self.assertEqual(target[0].get_text(), '')
            self.assertEqual(target[1].get_text().strip(), 'NE')
            config.skip_translation = True
            self.assertEqual(repair_rotated_labels(target, config, document), [])

    def test_identical_glyph_overprints_are_removed_but_separate_words_survive(self):
        def char(x, paint='0 g'):
            return NS(char_unicode='A', xobj_id=1, box=NS(x=x,y=10,x2=x+5,y2=20),
                      pdf_style=NS(font_id='F1',font_size=10,graphic_state=NS(passthrough_per_char_instruction=paint)))
        page = NS(page_layout=[],pdf_character=[char(10),char(10),char(20),char(10,'1 g')])
        deduplicate_text_layouts(page)
        self.assertEqual(len(page.pdf_character),3)

    def test_rotated_chinese_is_searchable_and_background_is_preserved(self):
        doc=fitz.open()
        page=doc.new_page(width=180,height=180)
        page.draw_rect(fitz.Rect(20,20,100,160),color=None,fill=(0.1,0.3,0.8))
        page.insert_text((65,40),'Classifier',rotate=270,fontsize=10,color=(1,1,1))
        labels=collect_rotated_labels(page)
        self.assertEqual(len(labels),1)
        self.assertEqual(labels[0]['rotate'],270)
        background_before=page.get_pixmap().pixel(25,25)
        draw_rotated_label(page,labels[0],'分类器')
        self.assertIn('分类器',unicodedata.normalize('NFKC',page.get_text()))
        self.assertNotIn('Classifier',page.get_text())
        self.assertEqual(page.get_pixmap().pixel(25,25),background_before)
        direction=page.get_text('dict')['blocks'][0]['lines'][0]['dir']
        self.assertAlmostEqual(direction[1],1)

    def test_rotated_latin_word_stays_on_one_line(self):
        doc=fitz.open()
        page=doc.new_page()
        label={'text':'Transformer Layer','rect':(30,40,45,80),'rotate':270,'size':7.68,'color':0}
        draw_rotated_label(page,label,'Transformer层')
        self.assertIn('Transformer层',unicodedata.normalize('NFKC',page.get_text()))
        lines=[l for b in page.get_text('dict')['blocks'] for l in b.get('lines',[])]
        self.assertEqual(len(lines),1)

    def test_numeric_rotated_ticks_are_preserved(self):
        doc=fitz.open()
        page=doc.new_page()
        page.insert_text((65,40),'12345',rotate=270,fontsize=10)
        self.assertEqual(collect_rotated_labels(page),[])

    def test_near_white_multiline_label_leaves_room_for_the_module_icon(self):
        doc=fitz.open()
        page=doc.new_page()
        page.insert_text((65,40),'Transformer\nLayer',rotate=270,fontsize=8,color=(254/255,1,1))
        labels=collect_rotated_labels(page)
        self.assertEqual(len(labels),1)
        self.assertGreater(labels[0]['text_rect'][1],labels[0]['rect'][1])

    def test_new_characters_work_after_reopening_a_subset_font_pdf(self):
        doc=fitz.open()
        page=doc.new_page()
        label={'text':'Classifier','rect':(30,40,45,90),'rotate':270,'size':8,'color':0}
        draw_rotated_label(page,label,'分类器')
        doc.subset_fonts()
        reopened=fitz.open(stream=doc.tobytes(),filetype='pdf')
        draw_rotated_label(reopened[0],label,'图块嵌入')
        self.assertIn('图块嵌入',unicodedata.normalize('NFKC',reopened[0].get_text()))

    def test_font_alias_is_fresh_even_when_the_font_count_matches_an_old_name(self):
        doc=fitz.open()
        page=doc.new_page()
        font=fitz.Font('cjk')
        page.insert_font(fontname='ZoteroRotatedLabels1',fontbuffer=font.buffer)
        page.insert_text((100,100),'分类器',fontname='ZoteroRotatedLabels1')
        doc.subset_fonts()
        reopened=fitz.open(stream=doc.tobytes(),filetype='pdf')
        label={'text':'Patch Embedding','rect':(30,40,45,90),'rotate':270,'size':8,'color':0}
        draw_rotated_label(reopened[0],label,'图块嵌入')
        names={f[4] for f in reopened[0].get_fonts()}
        self.assertIn('ZoteroRotatedLabels2',names)
        self.assertIn('图块嵌入',unicodedata.normalize('NFKC',reopened[0].get_text()))


if __name__=='__main__':
    unittest.main()
