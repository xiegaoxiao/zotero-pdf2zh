import unittest
import unicodedata
from types import SimpleNamespace as NS
import pymupdf as fitz

from utils.rotated_labels import collect_rotated_labels, draw_rotated_label
from utils.pdf_layout_repair import deduplicate_text_layouts


class FigureLabelTests(unittest.TestCase):
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
