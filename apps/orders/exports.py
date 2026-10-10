"""Excel documents: the supplier PO and the cost sheet. Both are laid out to
be printed (landscape, fitted to one page wide) and keep live formulas for
amounts and totals, so the file can be adjusted in Excel."""

import io

from django.conf import settings
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .services import line_costing, load_bom

NAVY = '10233F'
THIN = Side(style='thin', color='9AA5B1')
BOX = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
HEAD_FILL = PatternFill('solid', fgColor=NAVY)
LABEL_FILL = PatternFill('solid', fgColor='F3F6F9')
TOTAL_FILL = PatternFill('solid', fgColor='E3F3F3')
QTY, MONEY, RATE, CONS = '#,##0', '#,##0.00', '#,##0.0000', '0.000000'


def joined(values):
    """Distinct non-blank values, in first-seen order, as one string."""
    seen = []
    for value in values:
        if value and value not in seen:
            seen.append(value)
    return ', '.join(seen)


class Sheet:
    """Small helper around a worksheet: tracks the current row."""

    def __init__(self, title, widths):
        self.wb = Workbook()
        self.ws = self.wb.active
        self.ws.title = title[:31]
        self.row = 1
        self.cols = len(widths)
        for i, width in enumerate(widths, start=1):
            self.ws.column_dimensions[get_column_letter(i)].width = width
        self.ws.page_setup.orientation = 'landscape'
        self.ws.page_setup.paperSize = self.ws.PAPERSIZE_A4
        self.ws.page_setup.fitToWidth = 1
        self.ws.page_setup.fitToHeight = 0
        self.ws.sheet_properties.pageSetUpPr.fitToPage = True
        self.ws.print_options.horizontalCentered = True
        for side in ('left', 'right', 'top', 'bottom'):
            setattr(self.ws.page_margins, side, 0.4)

    def cell(self, col, value=None, *, bold=False, fmt=None, fill=None, align=None, box=True, color=None,
             size=None, wrap=False):
        c = self.ws.cell(row=self.row, column=col, value=value)
        if bold or color or size:
            c.font = Font(bold=bold, color=color, size=size)
        if fmt:
            c.number_format = fmt
        if fill:
            c.fill = fill
        if box:
            c.border = BOX
        c.alignment = Alignment(horizontal=align, vertical='center', wrap_text=wrap)
        return c

    def merge(self, col_from, col_to, row_to=None):
        self.ws.merge_cells(start_row=self.row, start_column=col_from, end_row=row_to or self.row, end_column=col_to)

    def title(self, text, right_text):
        mid = self.cols // 2
        self.cell(1, settings.COMPANY_NAME.upper(), bold=True, size=18, color=NAVY, box=False)
        self.merge(1, mid)
        self.cell(mid + 1, right_text, bold=True, size=14, color='FFFFFF', fill=HEAD_FILL, align='center', box=False)
        self.merge(mid + 1, self.cols)
        self.ws.row_dimensions[self.row].height = 26
        self.row += 1
        self.cell(1, settings.COMPANY_ADDRESS, box=False, color='445064')
        self.merge(1, self.cols)
        self.row += 2
        self.cell(1, text, bold=True, size=12, box=False)
        self.merge(1, self.cols)
        self.row += 2

    def info(self, pairs, spans):
        """Label/value pairs, two per row. spans = ((label cols), (value cols)) x 2."""
        for i in range(0, len(pairs), 2):
            for (label, value, *fmt), (lab, val) in zip(pairs[i:i + 2], spans):
                self.cell(lab[0], label, bold=True, fill=LABEL_FILL)
                for col in range(lab[0], val[1] + 1):
                    self.ws.cell(row=self.row, column=col).border = BOX
                if lab[1] > lab[0]:
                    self.merge(lab[0], lab[1])
                self.cell(val[0], value if value not in (None, '') else '—', fmt=fmt[0] if fmt else None, align='left')
                if val[1] > val[0]:
                    self.merge(val[0], val[1])
            self.row += 1
        self.row += 1

    def header(self, labels):
        """Column headings of the main table; repeated on every printed page."""
        for col, label in enumerate(labels, start=1):
            self.cell(col, label, bold=True, color='FFFFFF', fill=HEAD_FILL, align='center', wrap=True)
        self.ws.row_dimensions[self.row].height = 30
        self.ws.print_title_rows = f'{self.row}:{self.row}'
        self.row += 1

    def signatures(self, prepared_by):
        self.row += 3
        third = self.cols // 3
        for i, (name, label) in enumerate([(prepared_by, 'Prepared by'), ('', 'Checked by'),
                                           ('', 'Authorized signature')]):
            first = 1 + i * third
            last = first + third - 2
            c = self.ws.cell(row=self.row, column=first, value=name)
            c.font = Font(bold=True)
            c.alignment = Alignment(horizontal='center')
            self.ws.merge_cells(start_row=self.row, start_column=first, end_row=self.row, end_column=last)
            for col in range(first, last + 1):
                self.ws.cell(row=self.row, column=col).border = Border(bottom=Side(style='thin', color='333333'))
            c = self.ws.cell(row=self.row + 1, column=first, value=label)
            c.alignment = Alignment(horizontal='center')
            self.ws.merge_cells(start_row=self.row + 1, start_column=first, end_row=self.row + 1, end_column=last)

    def response(self, filename):
        out = io.BytesIO()
        self.wb.save(out)
        response = HttpResponse(
            out.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        safe = ''.join(ch if ch.isalnum() or ch in '-_ ' else '-' for ch in filename).strip()
        response['Content-Disposition'] = f'attachment; filename="{safe}.xlsx"'
        return response


# --------------------------------------------------------------------------
# supplier PO
# --------------------------------------------------------------------------

def po_lines_with_detail(po):
    """The PO's lines, each carrying the detail of the BOM rows it was raised
    from: placement, body color and garment size."""
    lines = list(po.lines.prefetch_related('bom_rows__item__line__assortment'))
    for line in lines:
        rows = list(line.bom_rows.all())
        line.style = line.style or joined(row.item.line.style for row in rows)
        line.placement = joined(row.item.placement for row in rows)
        line.body_color = joined(row.body_color for row in rows) or ('All colors' if rows else '')
        line.garment_size = joined(row.size_label for row in rows)
    return lines


def supplier_po_xlsx(po, prepared_by):
    order = po.order
    sh = Sheet(po.po_no, [5, 21, 34, 18, 16, 18, 9, 12, 11, 8, 11, 14])
    sh.title(f'Purchase Order · {po.type_label}', po.po_no)
    sh.info([
        ('Supplier', po.supplier), ('PO date', po.po_date, 'dd mmm yyyy'),
        ('PI to', po.pi_to), ('PI to location', po.pi_to_location),
        ('PI no.', po.pi_no), ('LC no.', po.lc_no),
        ('Buyer', order.buyer), ('Buyer PO', order.po_number),
        ('Factory', order.factory), ('Factory location', po.factory_location),
        ('Destination', po.destination), ('Required delivery', po.delivery_date, 'dd mmm yyyy'),
        ('ETD', po.etd, 'dd mmm yyyy'), ('ETA', po.eta, 'dd mmm yyyy'),
    ], spans=(((1, 2), (3, 5)), ((6, 7), (8, 12))))

    sh.header(['#', 'Style', 'Item', 'Placement', 'Body color', 'Color combination', 'Size', 'Spec', 'Qty', 'Unit',
               'Price', 'Amount'])
    first = sh.row
    for n, line in enumerate(po_lines_with_detail(po), start=1):
        for col, value in enumerate([n, line.style, line.description, line.placement, line.body_color, line.color,
                                     line.garment_size, line.spec], start=1):
            sh.cell(col, value, wrap=col in (2, 3, 4, 5, 6), align='center' if col == 1 else None)
        sh.cell(9, float(line.qty), fmt=QTY)
        sh.cell(10, line.unit)
        sh.cell(11, float(line.price) if line.price is not None else None, fmt=RATE)
        sh.cell(12, f'=I{sh.row}*K{sh.row}', fmt=MONEY)
        sh.row += 1
    last = sh.row - 1
    sh.cell(1, f'Total ({order.currency})', bold=True, fill=TOTAL_FILL, align='right')
    for col in range(2, 12):
        sh.cell(col, fill=TOTAL_FILL)
    sh.merge(1, 11)
    sh.cell(12, f'=SUM(L{first}:L{last})' if last >= first else 0, bold=True, fmt=MONEY, fill=TOTAL_FILL)
    sh.row += 1

    if po.notes:
        sh.row += 1
        sh.cell(1, f'Notes: {po.notes}', box=False, wrap=True)
        sh.merge(1, sh.cols)
        sh.ws.row_dimensions[sh.row].height = 15 * (po.notes.count('\n') + 1 + len(po.notes) // 120)
    sh.signatures(prepared_by)
    return sh.response(f'{po.po_no} {po.supplier}')


# --------------------------------------------------------------------------
# cost sheet
# --------------------------------------------------------------------------

def cost_sheet_xlsx(order, line, prepared_by):
    items = load_bom(line)
    costing = line_costing(line, items)
    sh = Sheet(f'Cost {line.style}', [5, 12, 34, 18, 15, 18, 13, 11, 11, 12, 8, 10, 14])
    sh.title(f'Cost Sheet · {line.style}', order.po_number)
    sh.info([
        ('Buyer', order.buyer), ('Order', order.order_no),
        ('Factory', order.factory), ('Ship date', order.ship_date, 'dd mmm yyyy'),
        ('Style', line.style), ('Item', line.description),
        ('Order qty (pcs)', line.qty, QTY), (f'FOB / pc ({order.currency})', float(line.unit_price), RATE),
    ], spans=(((1, 2), (3, 5)), ((6, 7), (8, 13))))
    qty_cell, fob_cell = f'$C${sh.row - 2}', f'$H${sh.row - 2}'

    # Color x size breakdown.
    sizes = line.active_size_indexes
    sh.cell(1, 'Color / Size', bold=True, fill=LABEL_FILL)
    sh.cell(2, fill=LABEL_FILL)
    sh.merge(1, 2)
    for i, idx in enumerate(sizes):
        sh.cell(3 + i, line.size_label(idx), bold=True, fill=LABEL_FILL, align='center')
    sh.cell(3 + len(sizes), 'Total', bold=True, fill=LABEL_FILL, align='center')
    sh.row += 1
    first = sh.row
    for row in line.assortment.all():
        sh.cell(1, row.color)
        sh.cell(2)
        sh.merge(1, 2)
        for i, idx in enumerate(sizes):
            sh.cell(3 + i, row.qty_at(idx), fmt=QTY)
        end = get_column_letter(2 + len(sizes))
        sh.cell(3 + len(sizes), f'=SUM(C{sh.row}:{end}{sh.row})' if sizes else 0, bold=True, fmt=QTY)
        sh.row += 1
    if sh.row > first:
        sh.cell(1, 'Total', bold=True, fill=TOTAL_FILL)
        sh.cell(2, fill=TOTAL_FILL)
        sh.merge(1, 2)
        for i in range(len(sizes) + 1):
            letter = get_column_letter(3 + i)
            sh.cell(3 + i, f'=SUM({letter}{first}:{letter}{sh.row - 1})', bold=True, fmt=QTY, fill=TOTAL_FILL)
        sh.row += 1
    sh.row += 1

    # Materials. Item-level cells are merged down the item's rows, like the source sheet.
    sh.header(['Sl', 'Type', 'Item', 'Placement', 'Body color', 'Color combination', 'Size / spec', 'Order qty',
               'Cons. / pc', 'Total req.', 'Unit', 'Price', 'TTL amount'])
    first = sh.row
    for n, item in enumerate(items, start=1):
        top = sh.row
        for row in item.row_list:
            size_spec = ' · '.join(v for v in [row.size_label if row.size_label != row.spec else '', row.spec] if v)
            is_top = sh.row == top
            sh.cell(1, n if is_top else None, align='center')
            sh.cell(2, item.get_category_display() if is_top else None)
            sh.cell(3, item.name if is_top else None, wrap=True)
            sh.cell(4, item.placement if is_top else None, wrap=True)
            sh.cell(5, row.body_label)
            sh.cell(6, row.color_combo)
            sh.cell(7, size_spec)
            sh.cell(8, row.order_qty, fmt=QTY)
            sh.cell(9, float(row.consumption), fmt=CONS)
            sh.cell(10, f'=H{sh.row}*I{sh.row}', fmt=MONEY)
            sh.cell(11, item.unit if is_top else None)
            sh.cell(12, float(row.price) if row.price is not None else None, fmt=RATE)
            sh.cell(13, f'=J{sh.row}*L{sh.row}', fmt=MONEY)
            sh.row += 1
        if sh.row - top > 1:
            for col in (1, 2, 3, 4, 11):
                sh.ws.merge_cells(start_row=top, start_column=col, end_row=sh.row - 1, end_column=col)
    last = sh.row - 1
    sh.cell(1, f'Total material cost ({order.currency})', bold=True, fill=TOTAL_FILL, align='right')
    for col in range(2, 13):
        sh.cell(col, fill=TOTAL_FILL)
    sh.merge(1, 12)
    sh.cell(13, f'=SUM(M{first}:M{last})' if last >= first else 0, bold=True, fmt=MONEY, fill=TOTAL_FILL)
    material_cell = f'$M${sh.row}'
    sh.row += 2

    # Other costs (left) and summary (right), side by side.
    start = sh.row
    sh.cell(1, 'Other costs', bold=True, fill=LABEL_FILL)
    sh.cell(2, fill=LABEL_FILL)
    sh.cell(3, fill=LABEL_FILL)
    sh.merge(1, 3)
    sh.cell(4, 'Per pc', bold=True, fill=LABEL_FILL, align='right')
    sh.row += 1
    extras_first = sh.row
    for extra in costing['extras']:
        sh.cell(1, extra.name)
        sh.cell(2)
        sh.cell(3)
        sh.merge(1, 3)
        sh.cell(4, float(extra.cost_per_pc), fmt=RATE)
        sh.row += 1
    sh.cell(1, 'Total other costs / pc', bold=True, fill=TOTAL_FILL)
    sh.cell(2, fill=TOTAL_FILL)
    sh.cell(3, fill=TOTAL_FILL)
    sh.merge(1, 3)
    sh.cell(4, f'=SUM(D{extras_first}:D{sh.row - 1})' if sh.row > extras_first else 0, bold=True, fmt=RATE,
            fill=TOTAL_FILL)
    extras_cell = f'$D${sh.row}'
    left_end = sh.row

    sh.row = start
    r = start  # summary rows: label in F:H, value in I:J
    summary = [
        ('Material / pc', f'={material_cell}/{qty_cell}', RATE),
        ('Material / dozen', f'=I{r}*12', RATE),
        ('Other costs / pc', f'={extras_cell}', RATE),
        ('Total cost / pc', f'=I{r}+I{r + 2}', RATE),
        ('FOB / pc', f'={fob_cell}', RATE),
        ('Margin / pc', f'=I{r + 4}-I{r + 3}', RATE),
        ('Margin %', f'=IF(I{r + 4}=0,0,I{r + 5}/I{r + 4})', '0.0%'),
        ('Order margin', f'=I{r + 5}*{qty_cell}', MONEY),
    ]
    for label, formula, fmt in summary:
        strong = label in ('Total cost / pc', 'Margin / pc', 'Order margin')
        sh.cell(6, label, bold=True, fill=LABEL_FILL)
        sh.cell(7, fill=LABEL_FILL)
        sh.cell(8, fill=LABEL_FILL)
        sh.merge(6, 8)
        sh.cell(9, formula, bold=strong, fmt=fmt, fill=TOTAL_FILL if strong else None)
        sh.cell(10, fill=TOTAL_FILL if strong else None)
        sh.merge(9, 10)
        sh.row += 1
    sh.row = max(sh.row, left_end + 1)
    if costing['unpriced']:
        sh.cell(1, f"{costing['unpriced']} row(s) have no price yet and count as zero.", box=False, color='C0392B')
        sh.merge(1, sh.cols)
        sh.row += 1
    sh.signatures(prepared_by)
    return sh.response(f'Cost sheet {order.po_number} {line.style}')
