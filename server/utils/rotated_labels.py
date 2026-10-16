"""Recover short rotated PDF labels omitted by BabelDOC's parser.

Use source text geometry rather than OCR. Draw only into the monolingual
document, before dual-page assembly, so original pages remain unchanged.
"""
import logging
import re
from pathlib import Path
from collections import Counter
import math

logger = logging.getLogger(__name__)


def collect_oblique_labels(page):
    """Keep source glyph origins and paint for short, non-axis-aligned labels."""
    labels = []
    for span in page.get_texttrace():
        dx, dy = span['dir']
        if min(abs(dx), abs(dy)) < .01 or span['wmode'] or span['type'] not in (0, 1):
            continue
        text = ''.join(chr(c[0]) for c in span['chars'])
        x0, y0, x1, y1 = span['bbox']
        if (not text.strip() or len(text) > 80 or max(x1-x0, y1-y0) > 210
                or re.search(r'arxiv|https?://|www\.', text, re.I)):
            continue
        labels.append(dict(span, text=text))
    return labels


def _source_font_codes(reader, xref, characters):
    # Invert the PDF encoding, not the font's Unicode cmap. Type3 fonts have no
    # extractable font file, and a trace glyph ID is not generally a PDF code.
    from pypdf import _cmap
    from pypdf.generic import IndirectObject
    font = reader.get_object(IndirectObject(xref, 0, reader))
    if hasattr(_cmap, 'get_encoding'):
        encoding, cmap = _cmap.get_encoding(font)
    else:
        _, _, encoding, cmap = _cmap.build_char_map_from_dict(200, font)
    if isinstance(encoding, dict):
        first, last = int(font.get('/FirstChar', 0)), int(font.get('/LastChar', 255))
        codes = {}
        for code, char in encoding.items():
            if max(0, first) <= code <= min(255, last):
                codes.setdefault(cmap.get(char, char), bytes([code]))
        return codes
    codes = {text: code.encode(encoding) for code, text in cmap.items()
             if isinstance(code, str) and isinstance(text, str)}
    name = str(font.get('/Encoding', ''))
    if not cmap and name.startswith('/Uni') and ('UTF16' in name or 'UCS2' in name):
        codes.update({char: char.encode('utf-16-be') for char in characters})
    return codes


def restore_oblique_labels(page, source_page, reader=None):
    """Graft a glyph-only vector layer, preserving the original PDF fonts.

    Source pages and files are never saved. Temporary pages in the source
    document hold only the selected glyphs, so no clipped body text, chart
    backgrounds, or duplicate searchable text is imported with the labels.
    """
    import pymupdf as fitz
    labels = collect_oblique_labels(source_page)
    if not labels:
        return []
    if reader is None:
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(source_page.parent.tobytes()))
    existing = [(chr(c[0]), c[2], span['dir']) for span in page.get_texttrace()
                for c in span['chars'] if span['type'] in (0, 1)]
    fonts = source_page.get_fonts(full=True)
    source = source_page.parent
    width, height = source_page.rect.width, source_page.rect.height
    font_codes, used_fonts, commands, report = {}, {}, [], []
    characters = {chr(c[0]) for label in labels for c in label['chars']}

    def font_key(name):
        return name.split('+')[-1]

    for label in labels:
        missing = []
        for char in label['chars']:
            text, origin = chr(char[0]), char[2]
            if any(text == t and math.dist(origin, p) < .15
                   and math.dist(label['dir'], direction) < .01
                   for t, p, direction in existing):
                continue
            missing.append(char)
        if not missing:
            continue
        candidates = [f[0] for f in fonts if font_key(f[3]) == font_key(label['font'])]
        selected = None
        for xref in dict.fromkeys(candidates):
            if xref not in font_codes:
                font_codes[xref] = _source_font_codes(reader, xref, characters)
            codes = font_codes[xref]
            if all(chr(c[0]) in codes for c in missing):
                selected = xref
                break
        if selected is None:
            logger.warning('Cannot restore oblique label with source font: %s', label['text'])
            continue
        alias = used_fonts.setdefault(selected, f'ZoteroOblique{len(used_fonts)}')
        color = label['color']
        if len(color) == 1:
            color = color * 3
        dx, dy = label['dir']
        length = math.hypot(dx, dy)
        dx, dy = dx/length, dy/length
        rgb = ' '.join(f'{v:.8f}' for v in color)
        opacity_name = f'ZoteroOpacity{len(report)}'
        commands.append(f'q /{opacity_name} gs {rgb} rg {rgb} RG '
                        f'{label["linewidth"]:.8f} w BT /{alias} {label["size"]:.8f} Tf '
                        f'{label["type"]} Tr\n')
        for char in missing:
            x, y = char[2]
            code = font_codes[selected][chr(char[0])].hex()
            commands.append(f'{dx:.8f} {-dy:.8f} {dy:.8f} {dx:.8f} '
                            f'{x:.8f} {height-y:.8f} Tm <{code}> Tj\n')
            existing.append((chr(char[0]), char[2], label['dir']))
        commands.append('ET Q\n')
        report.append({'source': label['text'], 'translation': label['text'],
                       'rect': label['bbox'], 'opacity': label['opacity'],
                       'mode': 'preserve_oblique_source', 'glyphs': len(missing)})
    if not report:
        return []
    # A new page avoids modifying shared resource dictionaries or source streams.
    overlay = source.new_page(width=width, height=height)
    font_resources = ' '.join(f'/{alias} {xref} 0 R' for xref, alias in used_fonts.items())
    opacities = ' '.join(f'/ZoteroOpacity{i} << /ca {item["opacity"]:.8f} '
                         f'/CA {item["opacity"]:.8f} >>' for i, item in enumerate(report))
    source.xref_set_key(overlay.xref, 'Resources',
                        f'<< /Font << {font_resources} >> /ExtGState << {opacities} >> >>')
    stream = source.get_new_xref()
    source.update_object(stream, '<< >>')
    source.update_stream(stream, ''.join(commands).encode('ascii'))
    overlay.set_contents(stream)
    page.show_pdf_page(page.rect, source, overlay.number, keep_proportion=False)
    return report


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
    # Grafting retains MuPDF source handles until the target closes. Load bytes
    # so the input file is not left locked on Windows after this hook returns.
    source_bytes = Path(config.input_file).read_bytes()
    with fitz.open(stream=source_bytes, filetype='pdf') as source:
        source_count = len(source)
        reader = None
        for il_page in document.page:
            number = il_page.page_number
            if number >= source_count or not config.should_translate_page(number + 1):
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
            if collect_oblique_labels(source[number]):
                config.raise_if_cancelled()
                if reader is None:
                    from io import BytesIO
                    from pypdf import PdfReader
                    reader = PdfReader(BytesIO(source_bytes))
                for item in restore_oblique_labels(pdf[number], source[number], reader):
                    item['page'] = number + 1
                    report.append(item)
    if report:
        logger.info('Restored %d rotated text labels', len(report))
    return report
