"""Recover short, quarter-turn PDF labels omitted by BabelDOC's parser.

Use source text geometry rather than OCR. Draw only into the monolingual
document, before dual-page assembly, so original pages remain unchanged.
"""
import logging
import re
from pathlib import Path
from collections import Counter

logger = logging.getLogger(__name__)


def collect_rotated_labels(page):
    labels, seen = [], set()
    for block in page.get_text('dict')['blocks']:
        lines = block.get('lines', [])
        if not lines or not all(abs(l['dir'][0]) < .01 and abs(l['dir'][1]) > .99 for l in lines):
            continue
        if len({1 if l['dir'][1] > 0 else -1 for l in lines}) != 1:
            continue
        text = ' '.join(''.join(s['text'] for s in l['spans']).strip() for l in lines).strip()
        if len(re.findall('[A-Za-z]', text)) < 3 or re.search(r'arxiv|https?://|www\.', text, re.I):
            continue
        rect = tuple(block['bbox'])
        if rect[3] - rect[1] > 210 or rect[2] - rect[0] > 90:
            continue
        rotate = 270 if lines[0]['dir'][1] > 0 else 90
        key = (text, rotate, *(round(v, 2) for v in rect))
        if key in seen:
            continue
        seen.add(key)
        spans = [s for l in lines for s in l['spans']]
        color = spans[0]['color']
        # Some Office exports report magenta in text extraction despite
        # painting white glyphs. Confirm the effective color from the source
        # rendering; never change a genuinely magenta label on white.
        if color == 0xff00ff:
            import pymupdf as fitz
            pix = page.get_pixmap(clip=fitz.Rect(rect), matrix=fitz.Matrix(2,2), alpha=False)
            colors = Counter(zip(*[iter(pix.samples)]*3))
            background = colors.most_common(1)[0][0]
            light_pixels = sum(n for rgb,n in colors.items() if min(rgb) > 230)
            if sum(background) < 450 and light_pixels > 10:
                color = 0xffffff
        text_rect = list(rect)
        near_white = all(((color >> shift) & 255) >= 245 for shift in (16,8,0))
        if near_white and len(lines) > 1 and rotate == 270:
            # Short white multiline module labels share the leading corner
            # with a frozen/trainable icon. Leave that original corner clear
            # when consolidating their translation into one rotated line.
            text_rect[1] += min(max(s['size'] for s in spans), (rect[3]-rect[1])*.23)
        labels.append({'text': text, 'rect': rect, 'text_rect': tuple(text_rect), 'rotate': rotate,
                       'size': max(s['size'] for s in spans), 'color': color})
    return labels


def draw_rotated_label(page, label, text):
    import pymupdf as fitz
    rect = fitz.Rect(label['rect'])
    # Preserve image and vector backgrounds when removing any surviving source
    # text. The unsupported labels in the reported PDF are absent already.
    surviving = page.get_text(clip=rect).strip()
    if surviving:
        page.add_redact_annot(rect, fill=False, cross_out=False)
        page.apply_redactions(images=0, graphics=0)
    rect = fitz.Rect(label.get('text_rect', label['rect']))
    rgb = fitz.sRGB_to_pdf(label['color'])
    font_file = Path.home()/'.cache/babeldoc/fonts/SourceHanSansCN-Regular.ttf'
    font = fitz.Font(fontfile=str(font_file)) if font_file.exists() else fitz.Font('cjk')
    # A previously saved PDF may already contain a subset under our old font
    # alias. A fresh resource name avoids reusing its incompatible glyph map.
    used_names = {f[4] for f in page.get_fonts()}
    number = len(used_names)
    font_name = f'ZoteroRotatedLabels{number}'
    while font_name in used_names:
        number += 1
        font_name = f'ZoteroRotatedLabels{number}'
    page.insert_font(fontname=font_name, fontbuffer=font.buffer)
    # Draw one unwrapped line using exactly the same font metrics for fitting
    # and painting. Legacy CJK textbox metrics can otherwise split Latin words.
    size = min(label['size'], (rect.width-.3) / (font.ascender-font.descender),
               (rect.height-.6) / max(font.text_length(text, fontsize=1), .1))
    length = font.text_length(text, fontsize=size)
    center = (rect.tl + rect.br) / 2
    cross_offset = (font.ascender + font.descender) * size / 2
    if label['rotate'] == 270:
        point = fitz.Point(center.x-cross_offset, center.y-length/2)
    else:
        point = fitz.Point(center.x+cross_offset, center.y+length/2)
    page.insert_text(point, text, fontname=font_name, fontsize=size,
                     rotate=label['rotate'], color=rgb)
    return {'source': label['text'], 'translation': text, 'fontsize': size, 'rect': tuple(rect)}


def repair_rotated_labels(pdf, config, document):
    import pymupdf as fitz
    if config.skip_translation or config.only_parse_generate_pdf:
        return []
    report = []
    translations = {}
    # input_file can be a split part; page numbering matches the in-memory PDF.
    with fitz.open(config.input_file) as source:
        for il_page in document.page:
            number = il_page.page_number
            if number >= len(source) or not config.should_translate_page(number + 1):
                continue
            for label in collect_rotated_labels(source[number]):
                config.raise_if_cancelled()
                if label['text'] not in translations:
                    source_text = label['text']
                    # A short domain glossary avoids translating patch as a
                    # software fix, without adding instructions to source text.
                    if source_text.lower().strip() == 'patch embedding' and config.lang_out.lower().startswith('zh'):
                        result = '图块嵌入'
                    else:
                        result = config.translator.translate(source_text)
                    if not isinstance(result, str) or not result.strip():
                        raise RuntimeError(f'Empty translation for rotated label: {label["text"]}')
                    translations[label['text']] = result.strip()
                item = draw_rotated_label(pdf[number], label, translations[label['text']])
                item['page'] = number + 1
                report.append(item)
    if report:
        logger.info('Restored %d rotated text labels', len(report))
    return report
