from pathlib import Path
from io import BytesIO
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
import pymupdf as fitz

# Synthetic, freely editable shapes; no third-party font or paper data.
order = ['.notdef','space','left','right','zero','two','three','four','unused']
builder = FontBuilder(1000, isTTF=True)
builder.setupGlyphOrder(order)
glyphs = {}
for i, name in enumerate(order):
    pen = TTGlyphPen(None)
    if name != 'space':
        pen.moveTo((40,0)); pen.lineTo((80+i*35,0))
        pen.lineTo((80+i*35,650)); pen.lineTo((40,650)); pen.closePath()
    glyphs[name] = pen.glyph()
builder.setupCharacterMap({32:'space',40:'left',41:'right',48:'zero',50:'two',51:'three',52:'four',65:'unused'})
mac = CmapSubtable.newSubtable(6)
mac.platformID, mac.platEncID, mac.language = 1,0,0
mac.cmap = {32:'space',40:'left',41:'right',48:'zero',50:'two',51:'three',52:'four',65:'unused'}
builder.font['cmap'].tables = [mac]
builder.setupGlyf(glyphs)
builder.setupHorizontalMetrics({name:(600,40) for name in order})
builder.setupHorizontalHeader(ascent=800,descent=-200)
builder.setupNameTable({'familyName':'Zotero Test Shapes','styleName':'Regular','uniqueFontIdentifier':'Zotero Test Shapes','fullName':'Zotero Test Shapes','psName':'ZoteroTestShapes'})
builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
builder.setupPost()
buffer = BytesIO(); builder.font.save(buffer)
pdf=fitz.open();page=pdf.new_page(width=200,height=70)
file=pdf.get_new_xref();pdf.update_object(file,'<<>>');pdf.update_stream(file,buffer.getvalue())
desc=pdf.get_new_xref();pdf.update_object(desc,f'<</Type /FontDescriptor /FontName /AAAAAB+ZoteroTestShapes /Flags 32 /FontBBox [0 -200 600 800] /ItalicAngle 0 /Ascent 800 /Descent -200 /CapHeight 650 /StemV 80 /FontFile2 {file} 0 R>>')
font=pdf.get_new_xref();pdf.update_object(font,f'<</Type /Font /Subtype /TrueType /BaseFont /AAAAAB+ZoteroTestShapes /Encoding /MacRomanEncoding /FirstChar 32 /LastChar 65 /Widths [{' '.join(['600']*34)}] /FontDescriptor {desc} 0 R>>')
pdf.xref_set_key(page.xref,'Resources',f'<</Font <</Font1 {font} 0 R>>>>')
stream=pdf.get_new_xref();pdf.update_object(stream,'<<>>');pdf.update_stream(stream,b'BT /Font1 14 Tf 1 0 0 1 20 35 Tm (20) Tj 45 0 Td (30) Tj 45 0 Td (40) Tj ET');page.set_contents(stream)
Path('tests/fixtures').mkdir(exist_ok=True)
pdf.save('tests/fixtures/sparse-macroman-ticks.pdf',deflate=True)
before=page.get_pixmap().samples
pdf.subset_fonts()
reopened=fitz.open(stream=pdf.tobytes(),filetype='pdf')
print('Reproduces visual corruption:',before!=reopened[0].get_pixmap().samples)
