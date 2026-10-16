"""Preserve front-page bylines, or translate each complete author row once."""
from collections import Counter
from copy import copy
import os
import re

AUTHOR_ENV = 'ZOTERO_PDF2ZH_TRANSLATE_AUTHORS'
_AUTHOR_LABELS = {'author', 'authors', 'author_name', 'author_names'}
_EXCLUDED = {'title', 'doc_title', 'paragraph_title', 'abandon', 'figure', 'table',
             'figure_caption', 'table_caption', 'isolate_formula', 'affiliation',
             'institution', 'email'}
_BODY_START = re.compile(r'^(?:abstract\b|摘要|摘\s*要|(?:1[.．]?|I[.．]?)?\s*introduction\b)', re.I)
_PROSE = re.compile(r'\b(?:abstract|university|department|institute|laboratory|school|'
                    r'we|our|this|paper|propose|present|is|are|was|were|using)\b', re.I)


def _characters(paragraph):
    for comp in paragraph.pdf_paragraph_composition:
        if getattr(comp, 'pdf_character', None) is not None:
            yield comp.pdf_character
        else:
            for field in ('pdf_line', 'pdf_same_style_characters', 'pdf_formula'):
                run = getattr(comp, field, None)
                if run is not None:
                    yield from run.pdf_character
                    break


def _name_row(paragraph):
    text = (paragraph.unicode or '').strip()
    if paragraph.layout_label in _AUTHOR_LABELS:
        return bool(text)
    if not text or len(text) > 350 or _PROSE.search(text):
        return False
    # Names/initials provide evidence; the title-to-abstract band supplies scope.
    return bool(re.search(r"\b(?:[A-Z][a-zÀ-ÿ'’-]+|[A-Z]\.)\s+(?:[A-Z][a-zÀ-ÿ'’-]+|[A-Z]\.)|"
                          r'\b(?:[A-Z]\.\s*)+[A-Z][a-zÀ-ÿ]+|\b[A-Z]{2,}\s+[A-Z]{2,}\b', text))


def _same_row(a, b):
    x, y = a.box, b.box
    overlap = min(x.y2, y.y2) - max(x.y, y.y)
    height = min(x.y2-x.y, y.y2-y.y)
    gap = max(0, max(x.x, y.x)-min(x.x2, y.x2))
    return (overlap >= height * 0.65 and gap <= height*2
            and a.xobj_id == b.xobj_id)


def _author_rows(page):
    if page.page_number != 0:
        return []
    paragraphs = [p for p in page.pdf_paragraph if getattr(p, 'box', None) is not None]
    crop = getattr(getattr(page, 'cropbox', None), 'box', None)
    if crop is None:
        return []
    titles = [p for p in paragraphs if p.layout_label in {'title', 'doc_title'}
              and p.box.y2 > crop.y + (crop.y2-crop.y)*0.55
              and not _BODY_START.match(p.unicode or '')]
    if not titles:
        return []
    title = max(titles, key=lambda p: p.box.y2)
    starts = [p.box.y2 for p in paragraphs if p.box.y2 < title.box.y
              and _BODY_START.match((p.unicode or '').strip())]
    bottom = max(starts) if starts else title.box.y - min(150, (crop.y2-crop.y)*0.2)
    candidates = [p for p in paragraphs if p.layout_label not in _EXCLUDED
                  and p.box.y >= bottom-1 and p.box.y2 <= title.box.y+1]
    rows, used = [], set()
    for seed in sorted(candidates, key=lambda p: (-p.box.y2, p.box.x)):
        if id(seed) in used or not _name_row(seed):
            continue
        row = [seed]
        while True:
            neighbors = [p for p in candidates if id(p) not in used
                         and all(p is not r for r in row) and any(_same_row(r,p) for r in row)]
            if not neighbors:
                break
            row.extend(neighbors)
        row.sort(key=lambda p: p.box.x)
        used.update(id(p) for p in row)
        rows.append(row)
    return rows


def prepare_author_paragraphs(page, config, environ=None):
    """Run before style/formula classification, when compositions are lines."""
    environ = os.environ if environ is None else environ
    translate = environ.get(AUTHOR_ENV, '0').lower() in {'1', 'true', 'yes', 'on'}
    preserved = getattr(config, '_zotero_author_paragraph_ids', set())
    alignments = getattr(config, '_zotero_author_alignments', {})
    count = 0
    for row in _author_rows(page):
        if not translate:
            for paragraph in row:
                preserved.add(id(paragraph))
                paragraph.debug_id = None
            count += len(row)
            continue
        # A detector may split an author's given name from their surname.
        # Merge same-baseline fragments before the model can guess each piece.
        paragraph = row[0]
        if len(row) > 1:
            comps = [c for p in row for c in p.pdf_paragraph_composition]
            if any(len(p.pdf_paragraph_composition) != 1 for p in row) or any(getattr(c, 'pdf_line', None) is None for c in comps):
                continue
            chars = sorted((c for p in row for c in _characters(p)), key=lambda c: c.box.x)
            box = copy(paragraph.box)
            box.x, box.x2 = min(p.box.x for p in row), max(p.box.x2 for p in row)
            box.y, box.y2 = min(p.box.y for p in row), max(p.box.y2 for p in row)
            line, composition = copy(comps[0].pdf_line), copy(comps[0])
            line.pdf_character, line.box = chars, copy(box)
            composition.pdf_line = line
            paragraph.pdf_paragraph_composition = [composition]
            paragraph.box = box
            paragraph.unicode = ' '.join((p.unicode or '').strip() for p in row)
            paragraph.layout_label = 'plain text'
            removed = {id(p) for p in row[1:]}
            page.pdf_paragraph[:] = [p for p in page.pdf_paragraph if id(p) not in removed]
        chars = [c for c in _characters(paragraph) if (c.char_unicode or '').strip()]
        if not chars:
            continue
        left, right = min(c.box.x for c in chars), max(c.box.x2 for c in chars)
        crop = page.cropbox.box
        centered = abs((left+right-crop.x-crop.x2)/2) <= (crop.x2-crop.x)*0.08
        baseline = Counter(round(c.box.y, 2) for c in chars).most_common(1)[0][0]
        alignments[id(paragraph)] = (left, right, baseline, centered)
        paragraph.first_line_indent = False
        count += 1
    config._zotero_author_paragraph_ids = preserved
    config._zotero_author_alignments = alignments
    return count


def align_translated_author(paragraph, config):
    alignment = getattr(config, '_zotero_author_alignments', {}).get(id(paragraph))
    if alignment is None or not re.search(r'[\u3400-\u9fff]', paragraph.unicode or ''):
        return
    chars = list({id(c): c for c in _characters(paragraph)}.values())
    if not chars:
        return
    left, right, baseline, centered = alignment
    lines = {}
    for char in chars:
        lines.setdefault(round(char.box.y, 1), []).append(char)
    # Do not move a wrapped translation beyond its original author block.
    if len(lines) != 1:
        return
    actual_left, actual_right = min(c.box.x for c in chars), max(c.box.x2 for c in chars)
    dx = (left+right-actual_left-actual_right)/2 if centered else left-actual_left
    dy = baseline-min(c.box.y for c in chars)
    for char in chars:
        boxes = {id(char.box): char.box}
        visual = getattr(char, 'visual_bbox', None)
        if visual is not None and visual.box is not None:
            boxes[id(visual.box)] = visual.box
        for box in boxes.values():
            box.x += dx
            box.x2 += dx
            box.y += dy
            box.y2 += dy
