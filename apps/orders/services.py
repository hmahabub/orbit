"""Workflow logic shared by the views and the demo seed command."""

import math
from collections import OrderedDict
from decimal import Decimal

from django.db import transaction

from .models import ZERO, SupplierPO, SupplierPOLine


def load_bom(line):
    """A style's BOM items with their rows, all sharing one `line` instance so
    the assortment is read once instead of once per row."""
    items = list(line.bom_items.prefetch_related('rows__po_lines'))
    for item in items:
        item.line = line
        item.row_list = list(item.rows.all())
        for row in item.row_list:
            row.item = item
    return items


def line_costing(line, items=None):
    items = load_bom(line) if items is None else items
    rows = [row for item in items for row in item.row_list]
    material_total = sum((row.amount for row in rows), ZERO)
    extras = list(line.cost_extras.all())
    extras_pc = sum((e.cost_per_pc for e in extras), ZERO)
    qty = Decimal(line.qty or 1)
    material_pc = material_total / qty
    total_pc = material_pc + extras_pc
    fob = line.unit_price or ZERO
    margin_pc = fob - total_pc
    return {
        'line': line,
        'extras': extras,
        'material_total': material_total,
        'material_pc': material_pc,
        'material_dz': material_pc * 12,
        'extras_pc': extras_pc,
        'total_pc': total_pc,
        'fob': fob,
        'margin_pc': margin_pc,
        'margin_pct': (margin_pc / fob * 100) if fob else ZERO,
        'margin_total': margin_pc * qty,
        'unpriced': sum(1 for row in rows if row.price is None),
        'row_count': len(rows),
    }


def unassigned_rows(order):
    """BOM rows not yet on any supplier PO, grouped by supplier."""
    groups = OrderedDict()
    for line in order.lines.prefetch_related('assortment'):
        for item in load_bom(line):
            for row in item.row_list:
                if not row.po_lines.all():
                    groups.setdefault(item.supplier.strip(), []).append(row)
    return groups


@transaction.atomic
def generate_supplier_pos(order):
    """One PO per supplier from every BOM row not yet on a PO. Rows for the
    same style/material/color/spec/price are merged into one PO line, with
    the quantity rounded up to a whole unit."""
    created = []
    for supplier, rows in unassigned_rows(order).items():
        if not supplier:
            continue
        po = SupplierPO.objects.create(order=order, supplier=supplier)
        merged = OrderedDict()
        for row in rows:
            item = row.item
            key = (item.line.style, item.name.strip(), row.color_combo, row.spec, item.unit, row.price)
            merged.setdefault(key, []).append(row)
        for (style, name, color, spec, unit, price), group in merged.items():
            qty = sum((r.requirement for r in group), ZERO)
            po_line = SupplierPOLine.objects.create(
                po=po, style=style, description=name, color=color, spec=spec, unit=unit, price=price,
                qty=Decimal(math.ceil(qty)),
            )
            po_line.bom_rows.set(group)
        created.append(po)
    return created
