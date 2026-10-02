"""The review queue as one Excel workbook, rewritten in place.

Asked for on 2026-10-01: one key on the review page writes what the page is
showing to a spreadsheet other people can work from. Always the same file, so
an export replaces the last one instead of leaving a new workbook each time,
and nothing is opened: the page says where the file is.

Written with the standard library. An .xlsx file is a zip of XML parts, and
this needs one sheet of text, numbers and links -- not a reason for a
dependency.
"""
import os
from pathlib import Path
import re
import tempfile
import zipfile
from xml.sax.saxutils import escape

from . import ranking
from .paths import ROOT

DEFAULT_PATH = ROOT / '.local' / 'exports' / 'review-queue.xlsx'
SHEET = 'Review queue'

COLUMNS = (('Status', 16), ('Company', 28), ('Title', 60), ('Location', 32), ('Posted', 12),
           ('Discovered', 12), ('Fit', 6), ('Band', 26), ('Published via', 22), ('Link', 12),
           ('Decided', 12), ('Reason', 40), ('Third-party listing', 40))

# XML 1.0 has no place for most control characters, and a provider's text
# sometimes carries them.
_INVALID = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]')
CELL_LIMIT = 32767


class ExportLocked(OSError):
    """The workbook is open somewhere that holds it, such as Excel on Windows."""


def status_of(source, group):
    """The tab a group is on, in the page's own words."""
    if source in ('applied', 'skipped'):
        return source.title()
    if group.get('less_related'):
        return 'Low relevance'
    if group.get('early_career'):
        return 'Early career'
    return 'To review' if source == 'pending' else 'Backlog'


def rows(entries):
    """One row per listing, from (source, group) pairs in the order given."""
    out = []
    for source, group in entries:
        bucket = group.get('bucket')
        band = ranking.LABELS[bucket] if isinstance(bucket, int) and 0 <= bucket < len(ranking.LABELS) else ''
        for job in group.get('jobs') or ():
            # The company's own link where the user found one: the row links to
            # it, and the third-party address it replaced is kept beside it.
            official = job.get('official_link')
            out.append([status_of(source, group), group.get('company') or '', group.get('title') or '',
                        job.get('location') or '', (job.get('posted_at') or '')[:10],
                        (job.get('first_seen') or '')[:10], group.get('confidence'), band,
                        'company site' if official else job.get('publisher') or job.get('provider_key') or '',
                        official or job.get('url') or '',
                        (group.get('at') or '')[:10], group.get('reason') or '',
                        (job.get('url') or '') if official else ''])
    return out


def _column(index):
    name = ''
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _text(value):
    return escape(_INVALID.sub('', str(value))[:CELL_LIMIT])


def _attribute(value):
    return escape(_INVALID.sub('', str(value)), {'"': '&quot;'})


def _sheet(table):
    link_column = [name for name, _ in COLUMNS].index('Link')
    last = f'{_column(len(COLUMNS) - 1)}{len(table) + 1}'
    lines = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
             'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">',
             f'<dimension ref="A1:{last}"/>',
             '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
             'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>',
             '<cols>' + ''.join(f'<col min="{i + 1}" max="{i + 1}" width="{width}" customWidth="1"/>'
                                for i, (_, width) in enumerate(COLUMNS)) + '</cols>', '<sheetData>']
    links = []
    for number, values in enumerate([[name for name, _ in COLUMNS]] + table, 1):
        cells = []
        for index, value in enumerate(values):
            ref = f'{_column(index)}{number}'
            if value is None or value == '':
                continue
            if number > 1 and index == link_column:
                links.append((ref, value))
                value = 'Open listing'
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{ref}"><v>{value:g}</v></c>' if isinstance(value, float)
                             else f'<c r="{ref}"><v>{value}</v></c>')
            else:
                style = ' s="1"' if number == 1 else ''
                cells.append(f'<c r="{ref}" t="inlineStr"{style}><is><t xml:space="preserve">'
                             f'{_text(value)}</t></is></c>')
        lines.append(f'<row r="{number}">' + ''.join(cells) + '</row>')
    lines.append('</sheetData>')
    lines.append(f'<autoFilter ref="A1:{last}"/>')
    if links:
        lines.append('<hyperlinks>' + ''.join(f'<hyperlink ref="{ref}" r:id="rId{i}"/>'
                                               for i, (ref, _) in enumerate(links, 1)) + '</hyperlinks>')
    lines.append('</worksheet>')
    relations = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/'
                           f'officeDocument/2006/relationships/hyperlink" Target="{_attribute(url)}" '
                           f'TargetMode="External"/>' for i, (_, url) in enumerate(links, 1))
                 + '</Relationships>')
    return '\n'.join(lines), relations, last


def workbook_bytes(table):
    """The .xlsx file for a table of rows under `COLUMNS`."""
    sheet, sheet_relations, last = _sheet(table)
    column, row = re.match(r'([A-Z]+)(\d+)$', last).groups()
    absolute = f'${column}${row}'
    parts = {
        '[Content_Types].xml':
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/>'
            '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.worksheet+xml"/>'
            '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.styles+xml"/></Types>',
        '_rels/.rels':
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        'xl/workbook.xml':
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            f'<sheets><sheet name="{SHEET}" sheetId="1" r:id="rId1"/></sheets>'
            '<definedNames><definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
            f"'{SHEET}'!$A$1:{absolute}</definedName></definedNames></workbook>",
        'xl/_rels/workbook.xml.rels':
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/worksheet" Target="worksheets/sheet1.xml"/>'
            '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            'relationships/styles" Target="styles.xml"/></Relationships>',
        # Two cell formats: the default, and bold for the header row.
        'xl/styles.xml':
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
            '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
            '<fills count="2"><fill><patternFill patternType="none"/></fill>'
            '<fill><patternFill patternType="gray125"/></fill></fills>'
            '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
            '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
            '</styleSheet>',
        'xl/worksheets/sheet1.xml': sheet,
        'xl/worksheets/_rels/sheet1.xml.rels': sheet_relations,
    }
    from io import BytesIO
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, text in parts.items():
            archive.writestr(name, text.encode('utf-8'))
    return buffer.getvalue()


def write(path, entries):
    """Replace the workbook at `path` with these groups. Returns the row count.

    Written beside the target and moved over it, so a reader never sees half a
    file. Windows refuses the move while Excel has the workbook open, and
    that is said plainly rather than writing a second file somewhere else.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    table = rows(entries)
    handle, temporary = tempfile.mkstemp(prefix='.review-queue-', suffix='.xlsx', dir=path.parent)
    try:
        with os.fdopen(handle, 'wb') as out:
            out.write(workbook_bytes(table))
        try:
            os.replace(temporary, path)
        except PermissionError as exc:
            raise ExportLocked(f'{path.name} is open in another program; close it and export again') from exc
    finally:
        Path(temporary).unlink(missing_ok=True)
    return len(table)
