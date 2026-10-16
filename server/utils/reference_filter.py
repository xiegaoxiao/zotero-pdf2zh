"""Keep detected bibliography paragraphs in their original PDF form.

The environment switch belongs to the child translation process, never to the
server's shared environment. Detection uses section headings and layout labels;
it deliberately does not guess that every final page is a bibliography.
"""
import logging
import os
import re

REFERENCE_ENV = 'ZOTERO_PDF2ZH_TRANSLATE_REFERENCES'
_PREFIX = r'(?:(?:[IVXLCDM]+|\d+)[.．、:]?\s*)?'
_REFERENCE = re.compile(_PREFIX + r'(?:references(?: and notes)?|bibliography|literature cited|works cited|参考文献|參考文獻)(?:\s*\(continued\))?\s*[:：]?', re.I)
_NEXT_SECTION = re.compile(
    _PREFIX + r'(?:appendix(?:\s+[A-Z\d]+)?|appendices|supplementary (?:material|information)|'
    r'acknowledg(?:e)?ments?|author contributions|biograph(?:y|ies)|附录|附錄|致谢|致謝)\s*[:：]?', re.I)
_REFERENCE_LABELS = {'reference', 'reference_content', 'reference_hybrid'}
_EXCLUDED_LABELS = {'abandon', 'figure', 'table', 'figure_caption', 'table_caption', 'caption'}


def _reading_order(page):
    """Order two-column pages without moving full-width section boundaries."""
    paragraphs = list(page.pdf_paragraph)
    crop = getattr(getattr(page, 'cropbox', None), 'box', None)
    if crop is None or not paragraphs or any(getattr(p, 'box', None) is None for p in paragraphs):
        return paragraphs
    width = crop.x2 - crop.x
    middle = (crop.x2 + crop.x) / 2
    # Full-width blocks divide the page into horizontal bands. Within each band
    # the left column is read completely before the right column.
    wide = sorted((p for p in paragraphs if p.box.x2-p.box.x > width*.7), key=lambda p: -p.box.y2)
    remaining = [p for p in paragraphs if p not in wide]
    result = []
    for boundary in [*wide, None]:
        band = [p for p in remaining if boundary is None or p.box.y2 > boundary.box.y2]
        result.extend(sorted(band, key=lambda p: ((p.box.x+p.box.x2)/2 >= middle, -p.box.y2, p.box.x)))
        remaining = [p for p in remaining if p not in band]
        if boundary is not None:
            result.append(boundary)
    return result


def preserve_reference_paragraphs(document, translation_config, environ=None):
    """Return preserved paragraph count, leaving source glyphs/styles intact."""
    environ = os.environ if environ is None else environ
    if environ.get(REFERENCE_ENV, '0').lower() in {'1', 'true', 'yes', 'on'}:
        return 0
    active = False
    preserved = set()
    for page in sorted(document.page, key=lambda p: p.page_number):
        for paragraph in _reading_order(page):
            label = (paragraph.layout_label or '').lower()
            if label in _EXCLUDED_LABELS:
                continue
            text = re.sub(r'\s+', ' ', paragraph.unicode or '').strip()
            if not text:
                continue
            if _REFERENCE.fullmatch(text):
                active = True
            elif _NEXT_SECTION.fullmatch(text):
                active = False
            elif label == 'title' and not re.match(r'^\[\d+\]', text):
                # A later section heading ends bibliography scope, including
                # article-specific appendix titles not in the explicit list.
                active = False
            if active or label in _REFERENCE_LABELS:
                preserved.add(id(paragraph))
                # Both LLM translation and automatic term extraction already
                # skip debug_id=None; legacy translation uses the explicit set.
                paragraph.debug_id = None
    translation_config._zotero_reference_paragraph_ids = preserved
    if preserved:
        logging.getLogger(__name__).info('Preserved %d bibliography paragraphs in the source language', len(preserved))
    return len(preserved)
