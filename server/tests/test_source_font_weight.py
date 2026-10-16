import unittest
from types import SimpleNamespace as NS
from utils.pdf_layout_repair import preserve_source_font_weight, prepare_continued_inputs, redistribute_continued_outputs


def paragraph(base, *runs):
    return NS(pdf_style=NS(font_id=base),pdf_paragraph_composition=[NS(pdf_same_style_characters=NS(pdf_style=NS(font_id=font),pdf_character=[NS(char_unicode=c) for c in text])) for font,text in runs])


class SourceFontWeightTests(unittest.TestCase):
    def setUp(self):
        self.fonts={'body':NS(bold=0),'bold':NS(bold=1),'italic':NS(bold=0),'unknown':NS(bold=None)}

    def test_mixed_weight_preserves_emphasis_in_both_directions(self):
        for base,other in [('body','bold'),('bold','body')]:
            p=paragraph(base,(other,'emphasis'),(base,' normal text'))
            self.assertFalse(preserve_source_font_weight(p,self.fonts,True))

    def test_uniform_text_and_italic_only_keep_the_requested_setting(self):
        for base,runs in [('body',[('body','text')]),('bold',[('bold','text')]),('body',[('italic','text'),('body',' body')])]:
            self.assertTrue(preserve_source_font_weight(paragraph(base,*runs),self.fonts,True))

    def test_unknown_fonts_and_whitespace_do_not_force_style_placeholders(self):
        for p in [paragraph('unknown',('bold','text')),paragraph('missing',('body','text')),paragraph('body',('bold',' '),('body','text'))]:
            self.assertTrue(preserve_source_font_weight(p,self.fonts,True))

    def test_enabled_rich_text_remains_enabled(self):
        self.assertFalse(preserve_source_font_weight(paragraph('body',('body','text')),self.fonts,False))

    def test_cross_page_sentence_tail_retains_its_original_bold_tag_only(self):
        first='How to reduce the negative impact of data deficiencies'
        second='and ambiguous annotations remains a challenge for DFER.'
        rest='<style id="3">Publicly available datasets are collected online.</style>'
        items=[{'id':0,'input':first},{'id':1,'input':'<style id="1">'+second+'</style>'+rest}]
        batch=NS(pages=[NS(page_number=0),NS(page_number=1)],paragraphs=[NS(unicode=first,layout_label='plain text',box=NS(x=0,x2=240,y=0,y2=12)),NS(unicode=second+' Publicly available datasets are collected online.',layout_label='plain text')])
        plans=prepare_continued_inputs(items,batch,[0,1])
        self.assertEqual(items[1]['input'],rest)
        sentence='如何减少数据缺失和模糊标注带来的负面影响，仍然是DFER面临的挑战。'
        results={0:sentence,1:'<style id="3">公开可用的数据集来自网络。</style>'}
        redistribute_continued_outputs(results,plans)
        self.assertTrue(results[1].startswith('<style id="1">'))
        tail=results[1].split('</style>')[0].split('>')[1]
        self.assertEqual(results[0]+tail,sentence)
        self.assertIn('</style><style id="3">公开可用',results[1])


if __name__=='__main__':
    unittest.main()
