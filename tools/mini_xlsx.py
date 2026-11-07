# -*- coding: utf-8 -*-
"""极简 xlsx 写入器：只用标准库（zipfile + XML），不依赖 openpyxl。

支持：多 sheet、表头加粗、列宽、数字/字符串。
"""

from __future__ import annotations

import os
import zipfile
from xml.sax.saxutils import escape

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
{sheets}
</Types>"""

ROOT_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<fonts count="2">
<font><sz val="11"/><name val="Calibri"/></font>
<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/></font>
</fonts>
<fills count="3">
<fill><patternFill patternType="none"/></fill>
<fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FF1F3864"/><bgColor indexed="64"/></patternFill></fill>
</fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="2">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""


def _col(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA"""
    name = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        name = chr(65 + rem) + name
    return name


def _cell(ref: str, value, style: int = 0) -> str:
    s = ' s="%d"' % style if style else ""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, s, value)
    text = "" if value is None else str(value)
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (
        ref, s, escape(text))


def write(path: str, sheets: list) -> None:
    """sheets = [(标题, 表头, 行)]"""
    n = len(sheets)
    sheet_tags = "".join(
        '<Override PartName="/xl/worksheets/sheet%d.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
        for i in range(n)
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES.replace("{sheets}", sheet_tags))
        z.writestr("_rels/.rels", ROOT_RELS)
        z.writestr("xl/styles.xml", STYLES)

        overrides = "".join(
            '<Override PartName="/xl/worksheets/sheet%d.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' % (i + 1)
            for i in range(n)
        )
        z.writestr("xl/workbook.xml",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                   'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                   "<sheets>" + "".join(
                       '<sheet name="%s" sheetId="%d" r:id="rId%d"/>' % (
                           escape(title[:31]), i + 1, i + 1)
                       for i, (title, _, _) in enumerate(sheets)) + "</sheets></workbook>")

        z.writestr("xl/_rels/workbook.xml.rels",
                   '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   + "".join(
                       '<Relationship Id="rId%d" '
                       'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                       'Target="worksheets/sheet%d.xml"/>' % (i + 1, i + 1)
                       for i in range(n))
                   + '<Relationship Id="rId%d" '
                     'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
                     'Target="styles.xml"/>' % (n + 1)
                   + "</Relationships>")

        for i, (title, headers, rows) in enumerate(sheets):
            xml = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
                   '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">']
            widths = []
            for c, h in enumerate(headers):
                lengths = [len(str(h))] + [len(str(r[c])) for r in rows[:200] if c < len(r)]
                widths.append(min(max(max(lengths) * 2, 10), 40))
            xml.append("<cols>" + "".join(
                '<col min="%d" max="%d" width="%d" customWidth="1"/>' % (c + 1, c + 1, w)
                for c, w in enumerate(widths)) + "</cols>")
            xml.append("<sheetData>")
            xml.append('<row r="1">' + "".join(
                _cell(_col(c) + "1", h, 1) for c, h in enumerate(headers)) + "</row>")
            for r, row in enumerate(rows, 2):
                xml.append('<row r="%d">' % r + "".join(
                    _cell(_col(c) + str(r), v) for c, v in enumerate(row)) + "</row>")
            xml.append("</sheetData></worksheet>")
            z.writestr("xl/worksheets/sheet%d.xml" % (i + 1), "".join(xml))
