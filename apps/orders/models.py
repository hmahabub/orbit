"""Orbit's whole workflow lives on one Order:

    Order -> Line Items -> Assortment (color x size) -> BOM (material
    allocation) -> Costing (admin only) -> Supplier PO

Buyer, factory, supplier and material names are plain text the user types
in — there are no separate master-data modules.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

ZERO = Decimal('0')

# Both size sets have 8 positions; an assortment row stores its quantities
# by position, so switching a line between the two sets only relabels them.
SIZE_SETS = {
    'letter': ['S', 'M', 'L', 'XL', 'XXL', '3XL', '4XL', '5XL'],
    'number': ['30', '32', '34', '36', '38', '40', '42', '44'],
}
SIZE_COUNT = 8

# What kind of material a BOM item is. Supplier POs are raised per type.
MATERIAL_TYPES = [
    ('fabric', 'Fabric'), ('lining', 'Lining'), ('interlining', 'Inter-lining'), ('pocketing', 'Pocketing'),
    ('trims', 'Trims'), ('accessories', 'Accessories'), ('labels', 'Labels'), ('packing', 'Packing'),
    ('other', 'Other'),
]


# --------------------------------------------------------------------------
# Orders
# --------------------------------------------------------------------------

class Order(models.Model):
    # Workflow tabs, in order. `stage` is the furthest tab unlocked so far.
    STAGE_ORDER, STAGE_LINES, STAGE_ASSORTMENT, STAGE_BOM, STAGE_COSTING, STAGE_PO = range(1, 7)

    STATUS_CHOICES = [('running', 'Running'), ('shipped', 'Shipped'), ('cancelled', 'Cancelled')]

    po_number = models.CharField('Buyer PO', max_length=40)
    buyer = models.CharField(max_length=100)
    factory = models.CharField(max_length=100, blank=True)
    ship_date = models.DateField(null=True, blank=True)
    currency = models.CharField(max_length=5, default='USD')
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='running')
    stage = models.PositiveSmallIntegerField(default=STAGE_LINES)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.order_no} ({self.po_number})'

    @property
    def order_no(self):
        return f'ORD-{self.pk:05d}' if self.pk else 'ORD-NEW'

    @property
    def total_qty(self):
        return sum(line.qty for line in self.lines.all())

    @property
    def total_amount(self):
        return sum((line.amount for line in self.lines.all()), ZERO)

    @property
    def descriptions(self):
        return ', '.join(line.description or line.style for line in self.lines.all())

    @property
    def ship_status(self):
        """green / amber (ships within 14 days) / red (past ship date)."""
        if self.status != 'running' or not self.ship_date:
            return 'green'
        days = (self.ship_date - timezone.localdate()).days
        if days < 0:
            return 'red'
        return 'amber' if days <= 14 else 'green'

    def advance_to(self, stage):
        if stage > self.stage:
            self.stage = stage
            self.save(update_fields=['stage', 'updated_at'])


class OrderLine(models.Model):
    SIZE_TYPE_CHOICES = [('letter', 'Letter sizes (S – 5XL)'), ('number', 'Number sizes (30 – 44)')]

    order = models.ForeignKey(Order, related_name='lines', on_delete=models.CASCADE)
    style = models.CharField(max_length=60)
    description = models.CharField('Item / Description', max_length=150, blank=True)
    qty = models.PositiveIntegerField('Qty (pcs)')
    unit_price = models.DecimalField('Price / pc', max_digits=10, decimal_places=4)
    size_type = models.CharField(max_length=10, choices=SIZE_TYPE_CHOICES, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f'{self.style} — {self.description}' if self.description else self.style

    @property
    def amount(self):
        return (self.unit_price or ZERO) * self.qty

    # ---- assortment helpers ------------------------------------------------

    @property
    def sizes(self):
        return SIZE_SETS.get(self.size_type or 'letter')

    def size_label(self, idx):
        return self.sizes[idx] if idx is not None and 0 <= idx < SIZE_COUNT else ''

    def _rows(self):
        # Cached per instance so BOM pages don't re-query for every row.
        if not hasattr(self, '_rows_cache'):
            self._rows_cache = list(self.assortment.all())
        return self._rows_cache

    @property
    def colors(self):
        return [row.color for row in self._rows()]

    @property
    def assortment_total(self):
        return sum(row.total for row in self._rows())

    def size_total(self, idx):
        return sum(row.qty_at(idx) for row in self._rows())

    def color_total(self, color):
        return sum(row.total for row in self._rows() if row.color == color)

    def cell_qty(self, color, idx):
        return sum(row.qty_at(idx) for row in self._rows() if row.color == color)

    @property
    def active_size_indexes(self):
        """Size positions that carry any quantity — only these get BOM rows."""
        return [i for i in range(SIZE_COUNT) if self.size_total(i)]

    @property
    def bom_qty(self):
        """Quantity a whole-order BOM row ('all colors, all sizes') uses."""
        return self.assortment_total or self.qty

    @property
    def assortment_complete(self):
        return bool(self.size_type and self._rows() and self.assortment_total == self.qty)


class AssortmentRow(models.Model):
    """One color on a line's color x size breakdown."""

    line = models.ForeignKey(OrderLine, related_name='assortment', on_delete=models.CASCADE)
    color = models.CharField(max_length=60)
    qtys = models.JSONField(default=list)  # SIZE_COUNT ints, by size position
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.line.style} / {self.color}'

    def qty_at(self, idx):
        try:
            return int(self.qtys[idx] or 0)
        except (IndexError, TypeError, ValueError):
            return 0

    @property
    def cells(self):
        return [self.qty_at(i) for i in range(SIZE_COUNT)]

    @property
    def total(self):
        return sum(self.cells)


# --------------------------------------------------------------------------
# BOM (material allocation)
# --------------------------------------------------------------------------

class BOMItem(models.Model):
    """One material on a style's BOM. Its rows split the requirement by body
    color and/or size, taking order quantities straight from the assortment.
    Consumption is always per piece: total requirement = order qty x
    consumption. Either can be typed; the other follows."""

    ALLOCATION_CHOICES = [
        ('all', 'All colors'),
        ('color', 'By color'),
        ('size', 'By size'),
        ('color_size', 'Color & size'),
    ]

    line = models.ForeignKey(OrderLine, related_name='bom_items', on_delete=models.CASCADE)
    category = models.CharField('Type', max_length=12, choices=MATERIAL_TYPES, default='trims')
    name = models.CharField('Item', max_length=150)
    placement = models.CharField(max_length=100, blank=True)
    supplier = models.CharField(max_length=100, blank=True)
    unit = models.CharField(max_length=20, default='Pcs')
    allocation = models.CharField(max_length=12, choices=ALLOCATION_CHOICES, default='color')
    consumption = models.DecimalField('Consumption / pc', max_digits=20, decimal_places=10, default=0)
    color_combo = models.CharField('Color combination', max_length=60, blank=True)  # blank = body color
    spec = models.CharField('Size / spec', max_length=60, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name

    def desired_keys(self):
        colors = self.line.colors or ['']
        sizes = self.line.active_size_indexes or [None]
        if self.allocation == 'color':
            return [(c, None) for c in colors]
        if self.allocation == 'size':
            return [('', s) for s in sizes]
        if self.allocation == 'color_size':
            return [(c, s) for c in colors for s in sizes]
        return [('', None)]

    def sync_rows(self):
        """Match rows to the current assortment: add rows for new colors/sizes,
        drop rows whose color/size is gone, keep everything already entered."""
        existing = {(r.body_color, r.size_idx): r for r in self.rows.all()}
        for pos, key in enumerate(self.desired_keys()):
            row = existing.pop(key, None)
            if row is None:
                color, size_idx = key
                BOMRow.objects.create(
                    item=self, body_color=color, size_idx=size_idx, position=pos,
                    color_combo=self.color_combo or color,
                    spec=self.spec or (self.line.size_label(size_idx) if size_idx is not None else ''),
                    consumption=self.consumption,
                )
            elif row.position != pos:
                row.position = pos
                row.save(update_fields=['position'])
        for stale in existing.values():
            stale.delete()


class BOMRow(models.Model):
    item = models.ForeignKey(BOMItem, related_name='rows', on_delete=models.CASCADE)
    body_color = models.CharField(max_length=60, blank=True)          # '' = all colors
    size_idx = models.PositiveSmallIntegerField(null=True, blank=True)  # None = all sizes
    color_combo = models.CharField(max_length=60, blank=True)
    spec = models.CharField(max_length=60, blank=True)
    consumption = models.DecimalField(max_digits=20, decimal_places=10, default=0)
    qty_override = models.PositiveIntegerField(null=True, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)  # set on Costing
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f'{self.item.name} / {self.body_label} / {self.size_label}'

    @property
    def body_label(self):
        return self.body_color or 'All colors'

    @property
    def size_label(self):
        return self.item.line.size_label(self.size_idx) if self.size_idx is not None else ''

    @property
    def auto_qty(self):
        line = self.item.line
        if self.body_color and self.size_idx is not None:
            return line.cell_qty(self.body_color, self.size_idx)
        if self.body_color:
            return line.color_total(self.body_color)
        if self.size_idx is not None:
            return line.size_total(self.size_idx)
        return line.bom_qty

    @property
    def order_qty(self):
        return self.qty_override if self.qty_override is not None else self.auto_qty

    @property
    def requirement(self):
        return Decimal(self.order_qty) * (self.consumption or ZERO)

    @property
    def amount(self):
        return self.requirement * (self.price or ZERO)


# --------------------------------------------------------------------------
# Costing (admin only)
# --------------------------------------------------------------------------

class CostExtra(models.Model):
    """Non-material cost per piece on a style: CM, washing, commercial, etc."""

    line = models.ForeignKey(OrderLine, related_name='cost_extras', on_delete=models.CASCADE)
    name = models.CharField(max_length=80)
    cost_per_pc = models.DecimalField('Cost / pc', max_digits=10, decimal_places=4)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.name


# --------------------------------------------------------------------------
# Supplier PO
# --------------------------------------------------------------------------

class SupplierPO(models.Model):
    STATUS_CHOICES = [('draft', 'Draft'), ('issued', 'Issued'), ('partial', 'Partly received'),
                      ('received', 'Received')]

    order = models.ForeignKey(Order, related_name='supplier_pos', on_delete=models.CASCADE)
    supplier = models.CharField(max_length=100)
    material_type = models.CharField('Type', max_length=12, choices=MATERIAL_TYPES, blank=True)  # '' = mixed
    po_date = models.DateField(default=timezone.localdate)
    delivery_date = models.DateField('Required delivery', null=True, blank=True)
    pi_no = models.CharField('PI no.', max_length=60, blank=True)
    lc_no = models.CharField('LC no.', max_length=60, blank=True)
    etd = models.DateField('ETD', null=True, blank=True)
    eta = models.DateField('ETA', null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
                                   related_name='supplier_pos')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Supplier PO'

    def __str__(self):
        return f'{self.po_no} — {self.supplier}'

    @property
    def type_label(self):
        return self.get_material_type_display() or 'Mixed'

    @property
    def po_no(self):
        """SPO-YY-xxxxx: year the PO was raised, then its running number."""
        if not self.pk:
            return 'SPO-NEW'
        raised = timezone.localtime(self.created_at) if self.created_at else timezone.localtime()
        return f'SPO-{raised:%y}-{self.pk:05d}'

    @property
    def total_amount(self):
        return sum((line.amount for line in self.lines.all()), ZERO)


class SupplierPOLine(models.Model):
    po = models.ForeignKey(SupplierPO, related_name='lines', on_delete=models.CASCADE)
    bom_rows = models.ManyToManyField(BOMRow, related_name='po_lines', blank=True)
    style = models.CharField(max_length=60, blank=True)
    description = models.CharField(max_length=150)
    color = models.CharField(max_length=60, blank=True)
    spec = models.CharField(max_length=60, blank=True)
    qty = models.DecimalField(max_digits=14, decimal_places=2)
    unit = models.CharField(max_length=20, blank=True)
    price = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)

    class Meta:
        ordering = ['id']

    def __str__(self):
        return self.description

    @property
    def amount(self):
        return self.qty * (self.price or ZERO)
