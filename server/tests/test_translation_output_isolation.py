import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from pypdf import PdfWriter, PdfReader
import server
from utils.config import Config
from utils.translation_outputs import publish_pdf_outputs, require_pdf_outputs


def write_pdf(path, title='new'):
    writer=PdfWriter()
    writer.add_blank_page(width=100,height=100)
    writer.add_metadata({'/Title':title})
    Path(path).parent.mkdir(parents=True,exist_ok=True)
    with open(path,'wb') as stream:
        writer.write(stream)


class TranslationOutputIsolationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.mono=self.root/'paper.no_watermark.zh-CN.mono.pdf'
        self.dual=self.root/'paper.no_watermark.zh-CN.dual.pdf'
        write_pdf(self.mono,'old mono')
        write_pdf(self.dual,'old dual')
        self.old=[self.mono.read_bytes(),self.dual.read_bytes()]
        self.translator=server.PDFTranslator.__new__(server.PDFTranslator)
        with redirect_stdout(io.StringIO()):
            self.config=Config({'engine':'pdf2zh_next','next_service':'openai'})
        self.config.update_config_file=Mock()
        self.addCleanup(patch.stopall)
        patch.object(server,'output_folder',str(self.root)).start()
        patch.object(server,'args',SimpleNamespace(enable_venv=False,enable_winexe=False),create=True).start()
        self.output_capture=redirect_stdout(io.StringIO())
        self.output_capture.__enter__()
        self.addCleanup(self.output_capture.__exit__,None,None,None)

    def assert_old_outputs_unchanged(self):
        self.assertEqual([self.mono.read_bytes(),self.dual.read_bytes()],self.old)

    def staged_outputs(self,cmd,both=True):
        folder=Path(cmd[cmd.index('--output')+1])
        write_pdf(folder/self.mono.name)
        if both:
            write_pdf(folder/self.dual.name)

    def test_zero_exit_with_old_files_and_no_new_outputs_is_failure(self):
        with patch.object(server,'execute_with_progress') as execute,patch.object(server,'_repair_damaged_pdf',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'本次任务'):
                self.translator.translate_pdf_next('paper.pdf',self.config)
            self.assertEqual(execute.call_count,1)
        self.assert_old_outputs_unchanged()

    def test_partial_output_after_retry_does_not_publish_or_index_missing_dual(self):
        with patch.object(server,'execute_with_progress',side_effect=lambda cmd,*a:self.staged_outputs(cmd,False)) as execute,patch.object(server,'_repair_damaged_pdf',return_value=str(self.root/'_repaired/paper.pdf')):
            with self.assertRaisesRegex(RuntimeError,'dual.pdf'):
                self.translator.translate_pdf_next('paper.pdf',self.config)
            self.assertEqual(execute.call_count,2)
        self.assert_old_outputs_unchanged()

    def test_repaired_retry_produces_a_complete_new_pair(self):
        calls=[]
        def execute(cmd,*args):
            calls.append(cmd)
            if len(calls)==2:
                self.staged_outputs(cmd)
        with patch.object(server,'execute_with_progress',side_effect=execute),patch.object(server,'_repair_damaged_pdf',return_value=str(self.root/'_repaired/paper.pdf')):
            result=self.translator.translate_pdf_next('paper.pdf',self.config)
        self.assertEqual(result,[str(self.mono),str(self.dual)])
        self.assertEqual(PdfReader(self.mono).metadata.title,'new')
        self.assertEqual(PdfReader(self.dual).metadata.title,'new')
        self.assertNotEqual(calls[0][calls[0].index('--output')+1],str(self.root))

    def test_nonzero_exit_is_failure_even_when_files_exist(self):
        def execute(cmd,*args):
            self.staged_outputs(cmd)
            raise subprocess.CalledProcessError(1,cmd)
        with patch.object(server,'execute_with_progress',side_effect=execute),patch.object(server,'_repair_damaged_pdf',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'引擎执行失败'):
                self.translator.translate_pdf_next('paper.pdf',self.config)
        self.assert_old_outputs_unchanged()

    def test_mono_only_request_does_not_require_a_dual_output(self):
        self.config.no_dual=True
        with patch.object(server,'execute_with_progress',side_effect=lambda cmd,*a:self.staged_outputs(cmd,False)):
            result=self.translator.translate_pdf_next('paper.pdf',self.config)
        self.assertEqual(result,[str(self.mono)])
        self.assertEqual(self.dual.read_bytes(),self.old[1])

    def test_incomplete_engine_result_reports_a_useful_error(self):
        self.translator.translate_pdf_next=Mock(return_value=[str(self.mono)])
        with self.assertRaisesRegex(RuntimeError,'文件不完整'):
            self.translator._execute_translate_job('test','paper.pdf',self.config,'pdf2zh_next')

    def test_failed_publication_rolls_back_both_old_outputs(self):
        stage=self.root/'stage'
        stage.mkdir()
        new_mono,new_dual=stage/self.mono.name,stage/self.dual.name
        write_pdf(new_mono)
        write_pdf(new_dual)
        replace=os.replace
        def fail_second(source,destination):
            if Path(source)==new_dual:
                raise PermissionError('locked')
            return replace(source,destination)
        with patch('utils.translation_outputs.os.replace',side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError,'已还原旧文件'):
                publish_pdf_outputs([str(new_mono),str(new_dual)],self.root)
        self.assert_old_outputs_unchanged()

    def test_invalid_pdf_is_not_a_successful_output(self):
        invalid=self.root/'invalid.pdf'
        invalid.write_bytes(b'not a PDF')
        with self.assertRaisesRegex(RuntimeError,'无法读取'):
            require_pdf_outputs([str(invalid)])


if __name__=='__main__':
    unittest.main()
