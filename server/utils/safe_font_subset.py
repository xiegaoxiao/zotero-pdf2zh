"""Subset added CJK fonts without changing source simple TrueType encodings.

MuPDF's native subsetter can remap a sparse MacRoman cmap incorrectly (for
example, extracted "20" still reads "20" but paints "43"). Keep the original
simple TrueType font graph intact while subsetting the remaining fonts.
"""
import re


def subset_fonts_preserving_source(pdf):
    protected = {}

    def remember(xref):
        if xref in protected:
            return
        obj = pdf.xref_object(xref, compressed=False)
        stream = pdf.xref_stream(xref) if pdf.xref_is_stream(xref) else None
        protected[xref] = (obj, stream)
        for ref in re.findall(r'(?<!\d)(\d+)\s+0\s+R\b', obj):
            remember(int(ref))

    for page in pdf:
        for font in page.get_fonts(full=True):
            if pdf.xref_get_key(font[0], 'Subtype') == ('name', '/TrueType'):
                remember(font[0])
    try:
        pdf.subset_fonts(fallback=False)
    finally:
        # Restore even when native subsetting fails partway through. xrefs stay
        # stable until the later save/garbage-collection step.
        for xref, (obj, stream) in protected.items():
            pdf.update_object(xref, obj)
            if stream is not None:
                pdf.update_stream(xref, stream, compress=True)
