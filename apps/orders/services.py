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


def pending_items(order):
    """BOM items that still have rows on no supplier PO, each with those rows
    (`pending_rows`) and their total requirement (`pending_req`)."""
    pending = []
    for line in order.lines.prefetch_related('assortment'):
        for item in load_bom(line):
            rows = [row for row in item.row_list if not row.po_lines.all()]
            if rows:
                item.pending_rows = rows
                item.pending_req = sum((row.requirement for row in rows), ZERO)
                pending.append(item)
    return pending


@transaction.atomic
def generate_supplier_pos(order):
    """One PO per supplier and material type from every BOM row not yet on a
    PO (materials without a supplier are skipped). Rows for the same
    style/material/color/spec/price become one PO line, with the quantity
    rounded up to a whole unit."""
    groups = OrderedDict()
    for item in pending_items(order):
        supplier = item.supplier.strip()
        if supplier:
            groups.setdefault((supplier, item.category), []).extend(item.pending_rows)

    created = []
    for (supplier, category), rows in groups.items():
        po = SupplierPO.objects.create(order=order, supplier=supplier, material_type=category)
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


def _absorb(target, source_type):
    """A PO that takes lines of another type becomes 'mixed'."""
    if target.material_type != source_type:
        target.material_type = ''
        target.save(update_fields=['material_type'])


@transaction.atomic
def move_po_lines(po, line_ids, target):
    """Move some of a PO's lines: to another PO of the same order (its pk),
    to a brand-new PO ('new'), or off the PO altogether ('pending' — the
    materials go back to the not-ordered list). An emptied PO is deleted.
    Returns the PO the lines ended up on, or None for 'pending'."""
    lines = po.lines.filter(pk__in=line_ids)
    if not lines:
        return po
    if target == 'pending':
        dest = None
        lines.delete()
    else:
        if target == 'new':
            dest = SupplierPO.objects.create(order=po.order, supplier=po.supplier, material_type=po.material_type,
                                             delivery_date=po.delivery_date)
        else:
            dest = SupplierPO.objects.get(pk=target, order=po.order)
            _absorb(dest, po.material_type)
        lines.update(po=dest)
    if not po.lines.exists():
        po.delete()
    return dest


@transaction.atomic
def merge_pos(pos):
    """Fold several POs of one supplier into the oldest one."""
    target, *others = sorted(pos, key=lambda po: po.pk)
    for po in others:
        _absorb(target, po.material_type)
        po.lines.update(po=target)
        po.delete()
    return target
