"""Visual regression for sparse MacRoman cmaps, using an original shape font."""
from pathlib import Path
import unittest
from hashlib import sha256
from unittest.mock import patch
import pymupdf as fitz

from utils.safe_font_subset import subset_fonts_preserving_source

FIXTURE = Path(__file__).with_name('fixtures') / 'sparse-macroman-ticks.pdf'


class SafeFontSubsetTests(unittest.TestCase):
    def test_fixture_uses_the_reported_sparse_macroman_encoding(self):
        with fitz.open(FIXTURE) as pdf:
            font = pdf[0].get_fonts()[0][0]
            self.assertEqual(pdf.xref_get_key(font, 'Encoding')[1], '/MacRomanEncoding')
            self.assertEqual(pdf[0].get_text().split(), ['20','30','40'])
            self.assertLess(min(pdf[0].get_pixmap().samples), 255)

    def test_protected_subset_preserves_pixels_after_reopening_and_repeating(self):
        with fitz.open(FIXTURE) as pdf:
            expected, text = sha256(pdf[0].get_pixmap().samples).digest(), pdf[0].get_text()
            for _ in range(2):
                subset_fonts_preserving_source(pdf)
            with fitz.open(stream=pdf.tobytes(garbage=4, deflate=True), filetype='pdf') as result:
                self.assertEqual(expected, sha256(result[0].get_pixmap().samples).digest())
                self.assertEqual(text, result[0].get_text())

    def test_added_cjk_fonts_remain_available_to_native_subsetting(self):
        with fitz.open(FIXTURE) as pdf:
            expected = sha256(pdf[0].get_pixmap().samples).digest()
            page = pdf.new_page(width=200, height=70)
            font_file = Path.home()/'.cache/babeldoc/fonts/SourceHanSansCN-Regular.ttf'
            if not font_file.exists():
                self.skipTest('BabelDOC cached CJK font unavailable')
            font = fitz.Font(fontfile=str(font_file))
            page.insert_font(fontname='AddedChinese', fontbuffer=font.buffer)
            page.insert_text((20,35), '中文', fontname='AddedChinese', fontsize=14)
            cjk_before = sha256(page.get_pixmap().samples).digest()
            size_before = len(pdf.tobytes(garbage=4,deflate=True))
            native = fitz.Document.subset_fonts
            calls = []
            def tracked_subset(document, **kwargs):
                calls.append(kwargs)
                return native(document, **kwargs)
            with patch.object(fitz.Document, 'subset_fonts', tracked_subset):
                subset_fonts_preserving_source(pdf)
            self.assertEqual(calls,[{'fallback':False}])
            data = pdf.tobytes(garbage=4,deflate=True)
            # Older MuPDF versions leave some Type0 fonts unchanged; newer
            # versions reduce them. Protecting source fonts must not grow them.
            self.assertLessEqual(len(data), size_before + 1024)
            with fitz.open(stream=data,filetype='pdf') as result:
                self.assertEqual(expected,sha256(result[0].get_pixmap().samples).digest())
                self.assertEqual(cjk_before,sha256(result[1].get_pixmap().samples).digest())

    def test_source_font_is_restored_if_subsetting_raises(self):
        with fitz.open(FIXTURE) as pdf:
            expected = sha256(pdf[0].get_pixmap().samples).digest()
            font = pdf[0].get_fonts()[0][0]
            def broken_subset(document, **kwargs):
                document.xref_set_key(font, 'Encoding', '/WinAnsiEncoding')
                raise RuntimeError('subset failure')
            with patch.object(fitz.Document, 'subset_fonts', broken_subset):
                with self.assertRaisesRegex(RuntimeError, 'subset failure'):
                    subset_fonts_preserving_source(pdf)
            self.assertEqual(pdf.xref_get_key(font,'Encoding')[1],'/MacRomanEncoding')
            with fitz.open(stream=pdf.tobytes(),filetype='pdf') as result:
                self.assertEqual(expected,sha256(result[0].get_pixmap().samples).digest())


if __name__ == '__main__':
    unittest.main()
