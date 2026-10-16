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
CONTINUATION_BREAK = '⟦PAGE_BREAK⟧'


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


def _prose_runs(source):
    """Read flat engine style tags without losing their original spelling."""
    runs, pieces, opening, position = [], [], '', 0
    tokens = re.split(r'(<[^>]*>)', source)
    for token in tokens:
        if not token:
            continue
        if token.startswith('<'):
            if re.fullmatch(r"<style id=['\"]\d+['\"]>", token) and not opening:
                opening = token
            elif token == '</style>' and opening:
                opening = ''
            else:
                return None
        else:
            pieces.append(token)
            runs.append((position, position + len(token), opening))
            position += len(token)
    if opening:
        return None
    return ''.join(pieces), runs


def _styled_slice(text, runs, start, end):
    parts = []
    for left, right, opening in runs:
        fragment = text[max(left, start):min(right, end)] if left < end and right > start else ''
        if fragment:
            parts.append(opening + fragment + ('</style>' if opening else ''))
    return ''.join(parts)


def _uniform_sentence_style(text, runs, start, end):
    styles = {opening for left, right, opening in runs
              if left < end and right > start and re.sub(r'\{v\d+\}', '', text[max(left, start):min(right, end)]).strip()}
    return next(iter(styles)) if len(styles) == 1 else None


def _sentence_ends(text):
    """Sentence boundaries in prose, excluding decimals and common abbreviations."""
    for match in re.finditer(r'''[.!?。！？]["'”’\)\]]*(?=\s|$|[A-Z])''', text):
        if text[match.start()] == '.':
            before = text[:match.start()]
            word = re.search(r'([A-Za-z.]+)$', before)
            word = word.group(1).lower() if word else ''
            if word in {'e.g', 'i.e', 'et al', 'al', 'fig', 'figs', 'eq', 'eqs',
                        'sec', 'secs', 'ref', 'refs', 'dr', 'mr', 'mrs', 'prof',
                        'vs', 'etc', 'no', 'vol', 'pp'} or len(word) == 1:
                continue
        yield match.end()


def _continuation_capacity(paragraph, fragment):
    """Estimate only the source sentence's space, not its entire paragraph."""
    size = getattr(getattr(paragraph, 'pdf_style', None), 'font_size', None) or 10
    box = getattr(paragraph, 'box', None)
    if box is None:
        return None
    line_capacity = max(1, (box.x2 - box.x) / size - 0.5)
    # Source glyphs give a better budget for a short tail in a long paragraph.
    chars = []
    for comp in getattr(paragraph, 'pdf_paragraph_composition', ()):
        line = getattr(comp, 'pdf_line', None)
        run = getattr(comp, 'pdf_same_style_characters', None)
        char = getattr(comp, 'pdf_character', None)
        chars.extend(line.pdf_character if line else run.pdf_character if run else [char] if char else [])
    source = ''.join(c.char_unicode or '' for c in chars)
    tail = re.search(re.escape(fragment).replace(r'\ ', r'\s*') + r'\s*$', source)
    if tail and len(source) == len(chars):
        width = sum(max(0, c.box.x2 - c.box.x) for c in chars[tail.start():tail.end()])
        if width > 0:
            return max(1, width / size)
    if box.y2 - box.y <= size * 1.6:
        return line_capacity
    return max(1, sum(1 if ord(c) > 0x2ff else .5 for c in fragment))


def prepare_continued_inputs(items, batch, selected_indices):
    """Translate a boundary sentence once, independently of surrounding prose.

    Prefixes/suffixes retain their own tags and formula placeholders. Formula
    tokens in the sentence are namespaced and constrained to their source page
    when splitting the translation. Unsupported styles keep the original path.
    """
    plans = []
    if len(batch.pages) != len(batch.paragraphs) or len(items) != len(selected_indices):
        return plans
    original = list(items)
    next_id = max((item['id'] for item in items), default=-1) + 1
    for n in range(len(original) - 1):
        a, b = selected_indices[n:n+2]
        pa, pb = batch.paragraphs[a], batch.paragraphs[b]
        left, right = original[n:n+2]
        if any(p['second'] == left['id'] for p in plans):
            continue
        if batch.pages[b].page_number != batch.pages[a].page_number + 1:
            continue
        if pa.layout_label not in BODY_LABELS or pb.layout_label not in BODY_LABELS:
            continue
        parsed_a, parsed_b = _prose_runs(left['input']), _prose_runs(right['input'])
        if parsed_a is None or parsed_b is None:
            continue
        first, runs_a = parsed_a
        second, runs_b = parsed_b
        if not first.strip() or first.rstrip()[-1] in '.!?。！？;；:' or not re.match(r'\s*[a-z]', second):
            continue
        start = list(_sentence_ends(first))
        start = start[-1] if start else 0
        while start < len(first) and first[start].isspace():
            start += 1
        end = next(_sentence_ends(second), None)
        if end is None:
            continue
        tail, head = first[start:], second[:end]
        style_a = _uniform_sentence_style(first, runs_a, start, len(first))
        style_b = _uniform_sentence_style(second, runs_b, 0, end)
        prose = re.sub(r'\{v\d+\}', '', tail + head)
        if style_a is None or style_b is None or re.search(r'[<>{}]', prose):
            continue
        capacity = _continuation_capacity(pa, tail)
        if capacity is None:
            continue
        prefix = _styled_slice(first, runs_a, 0, start)
        rest = _styled_slice(second, runs_b, end, len(second))
        plan = {'first': left['id'], 'second': right['id'],
                'first_opening': style_a, 'opening': style_b,
                'closing': '</style>' if style_b else '', 'capacity': capacity,
                'prefix_id': None, 'empty_second': not rest.strip(),
                'source_fraction': len(tail) / (len(tail) + len(head))}
        formulas, hints = {}, {}
        def namespace(text, item):
            def replace(match):
                token = '{v' + str(900000 + len(formulas)) + '}'
                formulas[token] = (item['id'], match.group())
                hint = item.get('formula_placeholders_hint', {}).get(match.group())
                if hint:
                    hints[token] = hint
                return token
            return re.sub(r'\{v\d+\}', replace, text)
        joined = namespace(tail.rstrip(), left) + ' ' + namespace(head.lstrip(), right)
        plan['formulas'] = formulas
        if prefix.strip():
            plan['prefix_id'] = next_id
            items.insert(items.index(left), dict(left, id=next_id, input=prefix))
            next_id += 1
        left['input'] = joined
        left['translation_hint'] = (
            'Translate this complete sentence fluently as a whole. '
            f'Insert {CONTINUATION_BREAK} once at a natural phrase boundary near its beginning, '
            f'within the first {capacity:.1f} em of translated text (one CJK character is about 1 em). '
            'This is a page-break instruction, not source content. Keep all formula placeholders '
            'exactly once, and do not repeat or omit any meaning on either side of the break.'
        )
        left.pop('formula_placeholders_hint', None)
        if hints:
            left['formula_placeholders_hint'] = hints
        if rest.strip():
            right['input'] = rest
        else:
            items.remove(right)
        plans.append(plan)
    return plans


def _wrap_continued_style(text, opening):
    # Formula compositions cannot be nested inside an engine style placeholder:
    # its parser would consume the formula as ordinary text and remove it.
    if not opening:
        return text
    return ''.join(part if re.fullmatch(r'\{v\d+\}', part)
                   else opening + part + '</style>'
                   for part in re.split(r'(\{v\d+\})', text) if part)


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
    # Validate every joined result before changing the caller's dictionary.
    restored = dict(results)
    for plan in plans:
        text = restored[plan['first']]
        formulas = plan.get('formulas', {})
        if not isinstance(text, str):
            raise ValueError('Unexpected joined prose sentence')
        suggested_cut = text.index(CONTINUATION_BREAK) if text.count(CONTINUATION_BREAK) == 1 else None
        text = text.replace(CONTINUATION_BREAK, '')
        prose = text
        lower, upper = 0, len(text)
        for token, (owner, original) in formulas.items():
            if text.count(token) != 1:
                raise ValueError('Missing or repeated continuation formula')
            position = text.index(token)
            if owner == plan['first']:
                lower = max(lower, position + len(token))
            else:
                upper = min(upper, position)
            prose = prose.replace(token, '')
        if re.search(r'[<>{}]', prose) or lower > upper:
            raise ValueError('Unexpected markup in joined prose sentence')
        # Approximate em widths conservatively; avoid cutting a Latin word.
        used, cut = 0.0, 0
        atoms = list(re.finditer(r'\{v\d+\}|.', text, re.S))
        advances = [1.0 if len(m.group()) > 1 or ord(m.group()) > 0x2ff else 0.55 for m in atoms]
        capacity = min(plan['capacity'], sum(advances) * plan.get('source_fraction', 1))
        for match, advance in zip(atoms, advances):
            char = match.group()
            if used + advance > capacity:
                break
            used += advance
            cut = match.end()
        if cut < len(text):
            punctuation = [i+1 for i,c in enumerate(text[:cut]) if c in '，、；：,;:']
            if punctuation and punctuation[-1] >= cut * 0.65:
                cut = punctuation[-1]
            elif re.match(r'[A-Za-z0-9]', text[cut-1:cut]) and re.match(r'[A-Za-z0-9]', text[cut:cut+1]):
                while cut > 0 and re.match(r'[A-Za-z0-9]', text[cut-1:cut]):
                    cut -= 1
        cut = max(lower, min(cut, upper))
        if suggested_cut is not None and lower <= suggested_cut <= upper:
            suggested_width = sum(a for m, a in zip(atoms, advances) if m.end() <= suggested_cut)
            if (0 < suggested_cut < len(text) and suggested_width <= capacity
                    and not (re.match(r'[A-Za-z0-9]', text[suggested_cut-1:suggested_cut])
                             and re.match(r'[A-Za-z0-9]', text[suggested_cut:suggested_cut+1]))):
                cut = suggested_cut
        if cut == 0:
            raise ValueError('Joined sentence cannot fit the first text line')
        opening = plan.get('first_opening', '')
        prefix_id = plan.get('prefix_id')
        prefix = restored.pop(prefix_id) if prefix_id is not None else ''
        suffix = '' if plan.get('empty_second') else restored[plan['second']]
        if not isinstance(prefix, str) or not isinstance(suffix, str):
            raise ValueError('Unexpected continuation prefix or suffix')
        head = text[:cut]
        tail = text[cut:]
        for token, (_, original) in formulas.items():
            head = head.replace(token, original)
            tail = tail.replace(token, original)
        restored[plan['first']] = prefix + _wrap_continued_style(head, opening)
        restored[plan['second']] = _wrap_continued_style(tail, plan['opening']) + suffix
    results.clear()
    results.update(restored)
