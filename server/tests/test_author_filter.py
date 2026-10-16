import io
from contextlib import redirect_stdout
from copy import deepcopy
from types import SimpleNamespace as NS
import unittest

from utils.author_filter import AUTHOR_ENV, prepare_author_paragraphs, align_translated_author
from utils.config import Config


def paragraph(text, x=50, y=660, width=200, label='plain text'):
    chars = [NS(char_unicode=c, box=NS(x=x+i*5, y=y, x2=x+(i+1)*5, y2=y+11),
                pdf_style=NS(font_size=11, font_id='source'), visual_bbox=None) for i,c in enumerate(text)]
    box = NS(x=x, y=y, x2=x+width, y2=y+13)
    return NS(unicode=text, box=box, xobj_id=0, debug_id='test', layout_label=label,
              first_line_indent=True,
              pdf_paragraph_composition=[NS(pdf_line=NS(box=deepcopy(box), pdf_character=chars))])


def page(*paragraphs, number=0):
    return NS(page_number=number, pdf_paragraph=list(paragraphs),
              cropbox=NS(box=NS(x=0,y=0,x2=612,y2=792)))


class AuthorFilterTests(unittest.TestCase):
    def fixture(self):
        title=paragraph('Vision Transformer for Facial Recognition',y=700,label='title')
        first=paragraph('Fanglei Xue, Qiangchang',width=120)
        second=paragraph('Wang, Zichang Tan, and Guodong Guo, Senior Member, IEEE',x=180,width=380)
        abstract=paragraph('Abstract—We introduce a method.',y=600)
        return page(title,first,second,abstract),title,first,second,abstract

    def test_default_preserves_both_byline_fragments_without_touching_source_glyphs(self):
        p,title,first,second,abstract=self.fixture()
        source=deepcopy((first.pdf_paragraph_composition,second.pdf_paragraph_composition))
        config=NS()
        self.assertEqual(prepare_author_paragraphs(p,config,{}),2)
        self.assertEqual((first.pdf_paragraph_composition,second.pdf_paragraph_composition),source)
        self.assertIsNone(first.debug_id)
        self.assertIsNone(second.debug_id)
        self.assertIsNotNone(title.debug_id)
        self.assertIsNotNone(abstract.debug_id)
        self.assertEqual(config._zotero_author_paragraph_ids,{id(first),id(second)})

    def test_opt_in_joins_split_given_name_and_surname_into_one_translation_input(self):
        p,title,first,second,abstract=self.fixture()
        config=NS()
        self.assertEqual(prepare_author_paragraphs(p,config,{AUTHOR_ENV:'1'}),1)
        self.assertEqual(len(p.pdf_paragraph),3)
        self.assertIs(p.pdf_paragraph[1],first)
        self.assertIn('Qiangchang Wang',first.unicode)
        self.assertEqual(first.unicode.count('Wang'),1)
        self.assertFalse(first.first_line_indent)
        self.assertIsNotNone(first.debug_id)
        self.assertFalse(config._zotero_author_paragraph_ids)
        self.assertIn(id(first),config._zotero_author_alignments)

    def test_affiliations_and_geography_are_not_treated_as_names(self):
        p,*_=self.fixture()
        affiliation=paragraph('University of Example',y=640,label='affiliation')
        location=paragraph('Beijing, China',y=625)
        p.pdf_paragraph.extend([affiliation,location])
        self.assertEqual(prepare_author_paragraphs(p,NS(),{}),2)
        self.assertIsNotNone(affiliation.debug_id)
        self.assertIsNotNone(location.debug_id)

    def test_body_names_later_pages_and_documents_without_title_are_not_filtered(self):
        for mode in ['later_page','no_title','body']:
            p,*_=self.fixture()
            if mode=='later_page':p.page_number=1
            elif mode=='no_title':p.pdf_paragraph=p.pdf_paragraph[1:]
            else:
                p.pdf_paragraph=[p.pdf_paragraph[0],p.pdf_paragraph[-1],paragraph('Alice Smith and Bob Jones.',y=400)]
            self.assertEqual(prepare_author_paragraphs(p,NS(),{}),0)

    def test_explicit_author_label_supports_non_latin_names(self):
        p=page(paragraph('研究方法',y=700,label='title'),
               paragraph('张三，李四',label='author'),paragraph('摘要：研究方法。',y=600))
        self.assertEqual(prepare_author_paragraphs(p,NS(),{}),1)

    def test_widely_separated_author_columns_are_not_merged(self):
        p=page(paragraph('Research on Models',y=700,label='title'),
               paragraph('Alice Smith',x=50,width=100),
               paragraph('Bob Jones',x=360,width=100),
               paragraph('Abstract—Our method.',y=600))
        self.assertEqual(prepare_author_paragraphs(p,NS(),{AUTHOR_ENV:'1'}),2)
        self.assertEqual(len(p.pdf_paragraph),4)

    def test_translated_single_row_retains_source_center_and_baseline(self):
        first,second=paragraph('薛方磊',x=20,y=650),paragraph('王强昌',x=50,y=650)
        chars=first.pdf_paragraph_composition[0].pdf_line.pdf_character+second.pdf_paragraph_composition[0].pdf_line.pdf_character
        first.pdf_paragraph_composition=[NS(pdf_character=c) for c in chars]
        # Check aliased visual/actual boxes are moved just once.
        chars[0].visual_bbox=NS(box=chars[0].box)
        config=NS(_zotero_author_alignments={id(first):(50,562,660,True)})
        align_translated_author(first,config)
        self.assertEqual((min(c.box.x for c in chars)+max(c.box.x2 for c in chars))/2,306)
        self.assertTrue(all(c.box.y==660 for c in chars))

    def test_left_aligned_byline_keeps_left_anchor(self):
        p=paragraph('中文作者',x=90,y=650)
        config=NS(_zotero_author_alignments={id(p):(50,250,660,False)})
        align_translated_author(p,config)
        chars=p.pdf_paragraph_composition[0].pdf_line.pdf_character
        self.assertEqual(min(c.box.x for c in chars),50)

    def test_missing_flag_defaults_off_and_explicit_values_are_parsed(self):
        for value,expected in [(None,False),('false',False),(False,False),('true',True),(True,True)]:
            data={'engine':'pdf2zh_next','next_service':'openai'}
            if value is not None:data['translateAuthors']=value
            with redirect_stdout(io.StringIO()):
                self.assertEqual(Config(data).translate_authors,expected)


if __name__=='__main__':
    unittest.main()
