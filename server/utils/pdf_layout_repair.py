"""Conservative BabelDOC repairs, copied into the selected managed engine.

No PDF text is deleted: nested duplicate detector boxes are removed before
character assignment; a paragraph-initial drop-cap word is normalized before
formula classification. Formula boxes, citations and normal superscripts stay
under the upstream rules.
"""
from copy import copy
import re

TEXT_LABELS = {'plain text', 'text', 'title', 'doc_title', 'paragraph_title'}
BODY_LABELS = {'plain text', 'text', 'paragraph_hybrid'}


def preserve_source_font_weight(paragraph, font_map, disable_rich_text):
    """Retain weight changes even when other rich-text translation is disabled.

    Uniform paragraphs already keep their base font. Mixed-weight paragraphs
    need the engine's style placeholders to carry source emphasis into Chinese,
    including the opening fragment of a sentence continued from another page.
    """
    if not disable_rich_text:
        return False
    style = getattr(paragraph, 'pdf_style', None)
    base = font_map.get(getattr(style, 'font_id', None))
    base_bold = getattr(base, 'bold', None)
    if base_bold is None:
        return True
    for comp in paragraph.pdf_paragraph_composition:
        run = getattr(comp, 'pdf_same_style_characters', None)
        if run is None or not any((c.char_unicode or '').strip() for c in run.pdf_character):
            continue
        font = font_map.get(run.pdf_style.font_id)
        bold = getattr(font, 'bold', None)
        if bold is not None and bool(bold) != bool(base_bold):
            return False
    return True


def is_numeric_label(paragraph):
    """Keep numeric tick runs at their original positions and font weights."""
    text = getattr(paragraph, 'unicode', None) or ''
    return bool(re.search(r'\d', text) and re.fullmatch(r'[\d\s.,+\-−–—~～%‰/:()\[\]×±^]+', text))


def deduplicate_text_layouts(page):
    # Some exported diagrams paint identical glyphs repeatedly at the same
    # position. Their English overprints look normal, but translating each
    # copy independently creates different, overlapping Chinese strings.
    seen, unique = set(), []
    for char in getattr(page, 'pdf_character', []):
        box, style = char.box, char.pdf_style
        graphic = getattr(style, 'graphic_state', None)
        paint = getattr(graphic, 'passthrough_per_char_instruction', None)
        key = (char.char_unicode, char.xobj_id, style.font_id, paint,
               round(style.font_size, 4), *(round(v, 4) for v in (box.x, box.y, box.x2, box.y2)))
        if key not in seen:
            unique.append(char)
            seen.add(key)
    if hasattr(page, 'pdf_character'):
        page.pdf_character[:] = unique
    candidates = [l for l in page.page_layout if l.class_name in TEXT_LABELS]
    def area(l):
        b = l.box
        return max(0, b.x2 - b.x) * max(0, b.y2 - b.y)
    # Keep the enclosing box; confidence breaks ties for exact duplicates.
    candidates.sort(key=lambda l: (area(l), l.conf or 0), reverse=True)
    kept, removed = [], set()
    for inner in candidates:
        b = inner.box
        for outer in kept:
            a = outer.box
            if inner.class_name != outer.class_name or area(inner) <= 0:
                continue
            ih, oh = b.y2 - b.y, a.y2 - a.y
            # A line box nested in a much taller paragraph can be meaningful.
            if min(ih, oh) < max(ih, oh) * 0.7:
                continue
            overlap = max(0, min(a.x2, b.x2) - max(a.x, b.x)) * max(0, min(a.y2, b.y2) - max(a.y, b.y))
            if overlap / area(inner) >= 0.98:
                removed.add(id(inner))
                break
        else:
            kept.append(inner)
    page.page_layout[:] = [l for l in page.page_layout if id(l) not in removed]


def normalize_drop_cap_words(page, config=None):
    for para in page.pdf_paragraph:
        if para.layout_label in {'title', 'doc_title'}:
            lines = [c.pdf_line for c in para.pdf_paragraph_composition if c.pdf_line]
            center = (para.box.x + para.box.x2) / 2
            if len(lines) >= 2 and all(abs((l.box.x + l.box.x2) / 2 - center) < (para.box.x2 - para.box.x) * 0.035 for l in lines):
                if config is not None:
                    if not hasattr(config, '_zotero_centered_titles'):
                        config._zotero_centered_titles = set()
                    config._zotero_centered_titles.add(id(para))
                para.first_line_indent = False
        if para.layout_label not in BODY_LABELS or not para.pdf_paragraph_composition:
            continue
        line = para.pdf_paragraph_composition[0].pdf_line
        if line is None or len(line.pdf_character) < 5:
            continue
        chars = line.pdf_character
        word = []
        for c in chars:
            if not c.char_unicode or not c.char_unicode.isascii() or not c.char_unicode.isalpha():
                break
            word.append(c)
        if not 2 <= len(word) <= 15 or len(chars) <= len(word):
            continue
        if not chars[len(word)].char_unicode.isspace():
            continue
        body = next((c for c in chars[len(word):] if c.char_unicode and not c.char_unicode.isspace()), None)
        if body is None or not word[0].char_unicode.isupper():
            continue
        size = body.pdf_style.font_size
        if not size or word[0].pdf_style.font_size < size * 2:
            continue
        if any(c.vertical or c.formula_layout_id for c in word):
            continue
        # TeX small capitals commonly use 80% of the body size. They are
        # ordinary letters, although the preceding drop cap makes the engine
        # mistake the entire suffix for a corner mark.
        if any(not 0.7 * size <= c.pdf_style.font_size <= 1.15 * size for c in word[1:]):
            continue
        # A drop cap starts the first prose line at its left edge, with the
        # following small capitals on that line, rather than an exponent.
        if abs(word[0].box.x - para.box.x) > size:
            continue
        if not all(abs(c.box.y - body.box.y) <= size * 0.4 for c in word[1:]):
            continue
        if word[0].box.y > body.box.y - size * 0.5:
            continue  # A large inline initial or superscript is not a drop cap.
        if any(getattr(b.box, 'x', 0) - getattr(a.box, 'x2', b.box.x) > size * 0.5
               for a, b in zip(word, word[1:])):
            continue
        for index, c in enumerate(word):
            c.pdf_style = copy(body.pdf_style)
            # Normalize the baseline as well as the font. Keeping the original
            # oversized glyph box can carry a false first-line height into
            # translation/typesetting, even after formula detection is fixed.
            c.box = copy(c.box)
            c.box.y, c.box.y2 = body.box.y, body.box.y + size
            if index + 1 < len(word):
                # Prevent the spacing heuristic from inserting "F ACIAL".
                c.box.x2 = word[index + 1].box.x
            visual = getattr(c, 'visual_bbox', None)
            if visual is not None and visual.box is not None:
                c.visual_bbox = copy(visual)
                c.visual_bbox.box = copy(c.box)
        text = getattr(para, 'unicode', None)
        if text:
            prefix = r'^\s*' + r'\s*'.join(re.escape(c.char_unicode) for c in word)
            para.unicode = re.sub(prefix, ''.join(c.char_unicode for c in word), text, count=1)


def center_translated_title(paragraph, config):
    """Center only a translated, originally centered multiline document title."""
    titles = getattr(config, '_zotero_centered_titles', set())
    was_centered = id(paragraph) in titles
    titles.discard(id(paragraph))
    if not was_centered or not re.search(r'[\u3400-\u9fff]', paragraph.unicode or ''):
        return
    comps = paragraph.pdf_paragraph_composition
    if not comps or any(not c.pdf_character for c in comps):
        return  # Leave mathematical title fragments to the upstream renderer.
    lines = {}
    for comp in comps:
        char = comp.pdf_character
        lines.setdefault(round(char.box.y, 1), []).append(char)
    for chars in lines.values():
        left = min(c.box.x for c in chars)
        right = max(c.box.x2 for c in chars)
        width = paragraph.box.x2 - paragraph.box.x
        if right - left > width + 0.5:
            continue
        offset = (paragraph.box.x + paragraph.box.x2 - left - right) / 2
        for c in chars:
            # Box and visual_bbox can refer to the same mutable object.
            boxes = {id(c.box): c.box}
            visual = getattr(c, 'visual_bbox', None)
            if visual is not None and visual.box is not None:
                boxes[id(visual.box)] = visual.box
            for box in boxes.values():
                box.x += offset
                box.x2 += offset


def prepare_continued_inputs(items, batch, selected_indices):
    """Join a safely recognizable cross-page prose sentence for translation.

    Only handle a single-line, unstyled first fragment and a plain or single-
    style sentence at the next page's start. Leave formulas and complex mixed
    styles to the upstream path. The model sees a complete sentence; its
    translation is subsequently split to fit the original first line.
    """
    plans = []
    if len(batch.pages) != len(batch.paragraphs):
        return plans
    for n in range(len(items) - 1):
        a, b = selected_indices[n:n+2]
        pa, pb = batch.paragraphs[a], batch.paragraphs[b]
        if batch.pages[b].page_number != batch.pages[a].page_number + 1:
            continue
        if pa.layout_label not in BODY_LABELS or pb.layout_label not in BODY_LABELS:
            continue
        first, second = (pa.unicode or '').strip(), (pb.unicode or '').strip()
        if not first or first[-1] in '.!?。！？;；:' or not re.match(r'[a-z]', second):
            continue
        source_a, source_b = items[n]['input'], items[n+1]['input']
        if len(source_a) > 120 or re.search(r'[<>{}.!?]', source_a):
            continue
        style = getattr(pa, 'pdf_style', None)
        size = getattr(style, 'font_size', None) or 10
        box = getattr(pa, 'box', None)
        if box is None or box.y2 - box.y > size * 1.6:
            continue
        match = re.match(r"^(<style id=['\"]\d+['\"]>)([^<>{}]*?[.!?])(</style>)(.*)$", source_b, re.S)
        if match:
            opening, prefix, closing, rest = match.groups()
        else:
            match = re.match(r'^([^<>{}]*?[.!?])(.*)$', source_b, re.S)
            if not match:
                continue
            prefix, rest = match.groups()
            opening = closing = ''
        # Do not empty a model input or consume the same middle paragraph twice.
        if not rest.strip() or any(p['second'] == items[n]['id'] for p in plans):
            continue
        items[n]['input'] = source_a.rstrip() + ' ' + prefix.lstrip()
        items[n+1]['input'] = rest
        plans.append({'first': items[n]['id'], 'second': items[n+1]['id'],
                      'opening': opening, 'closing': closing,
                      'capacity': max(1, (box.x2 - box.x) / size - 0.5)})
    return plans


def annotate_title_terms(items):
    """Supply domain/grammar hints only for recognizable research titles."""
    for item in items:
        if item.get('layout_label') not in {'title', 'doc_title'}:
            continue
        text = re.sub(r'<[^>]*>', '', item.get('input', ''))
        hints = []
        if re.search(r'\blandmark', text, re.I) and re.search(r'\bfac(?:e|ial)\b', text, re.I):
            hints.append('When translating into Chinese, facial landmarks are 面部关键点 (not geographic 地标); landmark-aware means 关键点感知.')
        if re.search(r'\badapting\b.+\bfor\b', text, re.I):
            hints.append('For a Chinese academic title, render Adapting X for Y as a concise noun phrase expressing model adaptation for a task, such as 面向Y的X适配, while preserving any preceding main title.')
        if hints:
            item['translation_hint'] = ' '.join(hints)


def redistribute_continued_outputs(results, plans):
    for plan in plans:
        text = results[plan['first']]
        if not isinstance(text, str) or re.search(r'[<>{}]', text):
            raise ValueError('Unexpected markup in joined prose sentence')
        # Approximate em widths conservatively; avoid cutting a Latin word.
        used, cut = 0.0, 0
        for i, char in enumerate(text):
            advance = 1.0 if ord(char) > 0x2ff else 0.55
            if used + advance > plan['capacity']:
                break
            used += advance
            cut = i + 1
        if cut < len(text):
            punctuation = [i+1 for i,c in enumerate(text[:cut]) if c in '，、；：,;:']
            if punctuation and punctuation[-1] >= cut * 0.65:
                cut = punctuation[-1]
            elif re.match(r'[A-Za-z0-9]', text[cut-1:cut]) and re.match(r'[A-Za-z0-9]', text[cut:cut+1]):
                while cut > 0 and re.match(r'[A-Za-z0-9]', text[cut-1:cut]):
                    cut -= 1
        if cut == 0:
            raise ValueError('Joined sentence cannot fit the first text line')
        results[plan['first']] = text[:cut].rstrip()
        tail = text[cut:].lstrip()
        results[plan['second']] = plan['opening'] + tail + plan['closing'] + results[plan['second']]
