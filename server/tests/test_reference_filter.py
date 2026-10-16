import io
import os
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from utils.reference_filter import REFERENCE_ENV, preserve_reference_paragraphs
from utils.config import Config
from utils.execute import execute_with_progress


def paragraph(text, x=50, top=700, label='plain text', width=220):
    return NS(unicode=text, debug_id=text, layout_label=label,
              box=NS(x=x, x2=x+width, y=top-20, y2=top),
              pdf_paragraph_composition=[object()])


def page(number, *paragraphs):
    return NS(page_number=number, pdf_paragraph=list(paragraphs),
              cropbox=NS(box=NS(x=0, x2=612)))


class ReferenceFilterTests(unittest.TestCase):
    def apply(self, *pages, env=None):
        config=NS()
        count=preserve_reference_paragraphs(NS(page=list(pages)),config,{} if env is None else env)
        return count,config

    def test_same_page_conclusion_and_cross_column_references(self):
        conclusion=paragraph('Our conclusion.',top=700)
        heading=paragraph('REFERENCES',top=400,label='title')
        left=paragraph('[1] A cited paper.',top=375)
        right=paragraph('[11] Another cited paper.',x=315,top=735)
        # Deliberately unordered geometric input: right column begins above
        # the reference heading, but follows it in reading order.
        count,_=self.apply(page(12,right,left,heading,conclusion))
        self.assertEqual(count,3)
        self.assertIsNotNone(conclusion.debug_id)
        self.assertTrue(all(p.debug_id is None for p in [heading,left,right]))

    def test_continues_across_pages_ignoring_running_headers(self):
        heading=paragraph('References',label='title')
        reference=paragraph('[2] Author, Paper, 2024.')
        header=paragraph('Journal name',top=770,label='abandon')
        count,_=self.apply(page(1,heading),page(2,header,reference))
        self.assertEqual(count,2)
        self.assertIsNotNone(header.debug_id)

    def test_appendix_resumes_translation(self):
        heading=paragraph('References',top=700)
        reference=paragraph('[1] Author, Paper.',top=650)
        appendix=paragraph('Appendix A',top=500,label='title')
        body=paragraph('Additional experiments.',top=450)
        count,_=self.apply(page(0,heading,reference,appendix,body))
        self.assertEqual(count,2)
        self.assertIsNotNone(appendix.debug_id)
        self.assertIsNotNone(body.debug_id)

    def test_full_width_boundary_after_two_column_references(self):
        heading=paragraph('References',x=50,top=700,width=510,label='title')
        left=paragraph('[1] First.',top=650)
        right=paragraph('[2] Second.',x=315,top=650)
        appendix=paragraph('Appendix',x=50,top=450,width=510,label='title')
        body=paragraph('More experiments.',top=400)
        count,_=self.apply(page(0,body,right,appendix,left,heading))
        self.assertEqual(count,3)
        self.assertIsNotNone(body.debug_id)

    def test_heading_variants(self):
        for heading in ['7. References','VII. REFERENCES','Bibliography','参考文献','參考文獻','References (continued)','Works Cited','References and Notes']:
            with self.subTest(heading=heading):
                self.assertEqual(self.apply(page(0,paragraph(heading)))[0],1)

    def test_prose_and_last_page_are_not_assumed_to_be_bibliography(self):
        prose=paragraph('References to previous work are discussed here.')
        citation=paragraph('[15], AffectNet and other datasets improve performance.')
        self.assertEqual(self.apply(page(99,prose,citation))[0],0)

    def test_explicit_layout_label_without_heading(self):
        reference=paragraph('Author, Paper, 2024.',label='reference_content')
        body=paragraph('Unrelated content.',top=600)
        self.assertEqual(self.apply(page(0,reference,body))[0],1)
        self.assertIsNotNone(body.debug_id)

    def test_opt_in_leaves_all_content_translatable(self):
        heading=paragraph('References')
        reference=paragraph('[1] Author, Paper.',top=600)
        count,_=self.apply(page(0,heading,reference),env={REFERENCE_ENV:'1'})
        self.assertEqual(count,0)
        self.assertIsNotNone(reference.debug_id)

    def test_source_content_geometry_and_styles_stay_unchanged(self):
        reference=paragraph('References')
        composition=reference.pdf_paragraph_composition
        box=reference.box
        count,config=self.apply(page(0,reference))
        self.assertEqual(count,1)
        self.assertEqual(reference.unicode,'References')
        self.assertIs(reference.pdf_paragraph_composition,composition)
        self.assertIs(reference.box,box)
        self.assertIn(id(reference),config._zotero_reference_paragraph_ids)


class ReferenceSettingTests(unittest.TestCase):
    def test_old_clients_default_to_skip_and_explicit_opt_in_is_parsed(self):
        for raw,expected in [(None,False),('false',False),(False,False),('true',True),(True,True)]:
            request={'engine':'pdf2zh_next','next_service':'openai'}
            if raw is not None:
                request['translateReferences']=raw
            with self.subTest(raw=raw),redirect_stdout(io.StringIO()):
                self.assertEqual(Config(request).translate_references,expected)

    def test_child_environment_is_isolated_and_overrides_managed_environment(self):
        manager=Mock()
        manager.get_command_and_env.return_value=(['python','translate.py'],{REFERENCE_ENV:'stale'})
        with patch.dict(os.environ,{REFERENCE_ENV:'parent'}), \
             patch('utils.execute.prepare_deepseek_runtime_command',side_effect=lambda cmd,env:cmd), \
             patch('utils.execute._execute_with_inherit') as windows, \
             patch('utils.execute._execute_with_pty') as unix, \
             redirect_stdout(io.StringIO()):
            for value in ['0','1']:
                execute_with_progress(['translate'],None,NS(enable_venv=True),manager,{REFERENCE_ENV:value})
                child=(windows if os.name=='nt' else unix).call_args.args[1]
                self.assertEqual(child[REFERENCE_ENV],value)
                self.assertEqual(os.environ[REFERENCE_ENV],'parent')


if __name__=='__main__':
    unittest.main()
