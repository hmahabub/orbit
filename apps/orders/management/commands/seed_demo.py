"""Loads the demo data from 'order demo.xlsx' and 'material allocation and
costing demo.xlsx': four N&I orders, the first one (WC6916 TRAVIS) carried all
the way through assortment, BOM, costing and supplier POs.

    python manage.py seed_demo            # adds demo users + orders
    python manage.py seed_demo --reset    # wipes all orders first
"""

import datetime
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.orders.models import AssortmentRow, BOMItem, CostExtra, Order, OrderLine, SupplierPO
from apps.orders.services import generate_supplier_pos

COLORS = ['OYSTER', 'STEEL', 'FERN CAMO']
ASSORTMENT = {  # S, M, L, XL
    'OYSTER': [836, 1672, 1672, 836],
    'STEEL': [668, 1336, 1336, 668],
    'FERN CAMO': [836, 1672, 1672, 836],
}

# Consumption is per piece (the sheet's
# per-dozen fabric figures are divided by 12; "6 pcs per poly bag" is 1/6).
# name, placement, supplier, unit, allocation, consumption / pc,
# color combo (str, or {body color: combo}), spec (str, or [spec per size]), price
BLACK_POCKET = {'OYSTER': 'White', 'STEEL': 'BLACK', 'FERN CAMO': 'BLACK'}
BOM = [
    ('100% COTTON HERRINGBONE TWILL 16x12 270-280g (wash)', 'Main body', 'Roundstone', 'Yds', 'color',
     '1.478070', '', '58"', '1.85'),
    ('TC Pocketing', 'Pocketing', 'Mashfiq', 'Yds', 'color', '0.553628', BLACK_POCKET, '60"', '0.55'),
    ('Fuse Interlining', 'Cargo Pocket Flap', 'Sunshine', 'Yds', 'all', '0.085826', 'White', '40"', '0.40'),
    ('4.2 CM elastic', 'at waist', 'Sunshine', 'Pcs', 'color', '1',
     {'OYSTER': 'White', 'STEEL': 'Black', 'FERN CAMO': 'Black'}, '4.2 CM', '0.03'),
    ('METAL GROMMET 10MM', 'at waist', 'Sunshine', 'Pcs', 'color', '2', 'Matt Black Enamel', '10 mm', '0.0085'),
    ('PIN POINT DRAW CORD with plastic tip end black', 'waist', 'Sunshine', 'Pcs', 'size', '1',
     'Black/Reflective', ['52"', '54"', '56"', '58"'], '0.04'),
    ('#5 VISLON ZIPPER Closed end', 'at pocket', 'Faiza', 'Pcs', 'size', '1', 'Black', '6"', '0.06'),
    ('1" Nylon Webbing tape', 'Cargo Pocket Flap', 'Sunshine', 'Yds', 'color', '0.111111', 'Black', '1"', '0.12'),
    ('1" VELCRO SQUARE CLOSURE', 'Cargo Pocket Flap', 'Sunshine', 'Yds', 'color', '0.090278', '', '1"', '0.35'),
    ('3/8" Grosgrain tape', 'at inside leg', 'Sunshine', 'Yds', 'color', '0.083333', '', '3/8"', '0.08'),
    ('Sewing Thread 20/3', 'For top stitch', 'Sunshine', 'Cone', 'color', '0', '', '20/3', '1.10'),
    ('Sewing Thread 40/2', 'overall garments', 'Sunshine', 'Cone', 'color', '0', '', '40/2', '1.10'),
    ('Sewing Thread 40/2', 'For pocketing', 'Sunshine', 'Cone', 'color', '0',
     {'OYSTER': 'White', 'STEEL': 'Black', 'FERN CAMO': 'Black'}, '40/2', '1.10'),
    ('Main Label (Brand: WXYZ) TR051', 'at inside waistband', 'Alif Enterprise', 'Pcs', 'all', '1',
     'BLACK', 'as per Artwork', '0.018'),
    ('PRINTED ALPHA SIZE LABEL TR169-B', 'inside waistband', 'Alif Enterprise', 'Pcs', 'size', '1', 'BLACK', '', '0.006'),
    ('Care Label', 'at side seam', 'Alif Enterprise', 'Pcs', 'all', '1', 'BLACK', '', '0.010'),
    ('Main Hangtag (Wxyz) TR056', 'at side seam', 'Alif Enterprise', 'Pcs', 'color', '1', '', '', '0.025'),
    ('Joker tag TR303', 'at side seam', 'Alif Enterprise', 'Pcs', 'size', '1', 'BLACK', '', '0.008'),
    ('Fit Tag TR335', 'at side seam', 'Alif Enterprise', 'Pcs', 'all', '1', 'BLACK', '', '0.012'),
    ('Tag pin', 'at side seam', 'Alif Enterprise', 'Pcs', 'all', '1', 'BLACK', '', '0.004'),
    ('Blister Poly Bag', '', 'Sunshine', 'Pcs', 'all', '0.166667', 'clear', '', '0.03'),
    ('Master Carton 7 Ply', '', 'Sunshine', 'Pcs', 'all', '0.041667', 'brown', '', '0.95'),
    ('Scotch tape', '', 'Sunshine', 'Roll', 'all', '0', 'BLACK', '', '0.80'),
    ('Gum Tape', '', 'Sunshine', 'Roll', 'all', '0', '', '', '0.90'),
]
# Material type by position in BOM: 3 fabrics, then trims, labels, packing.
CATEGORY_UPTO = [('fabric', 3), ('trims', 13), ('labels', 20), ('packing', 99)]
EXTRAS = [('CM', '0.55'), ('Washing', '0.18'), ('Commercial', '0.05')]

ORDERS = [
    ('WC6916', 'TRAVIS ZIP CARGO PANT', 'WC217G398 TRAVIS', datetime.date(2026, 12, 30)),
    ('WC6917', 'ZIP CARGO PANT', 'WC217G399', datetime.date(2026, 1, 15)),
    ('WC6918', 'CARGO PANT', 'WC217G400', None),
    ('WC6919', 'TRAVIS ZIP short pant', 'WC217G401', None),
]


class Command(BaseCommand):
    help = 'Load the Orbit demo orders (from the demo spreadsheets) and demo users.'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_true', help='Delete every existing order first.')

    @transaction.atomic
    def handle(self, *args, reset=False, **opts):
        User = get_user_model()
        admin, created = User.objects.get_or_create(
            username='admin', defaults={'is_staff': True, 'is_superuser': True, 'first_name': 'Admin'})
        if created:
            admin.set_password('admin123')
            admin.save()
        merch, created = User.objects.get_or_create(username='merchant', defaults={'first_name': 'Merchandiser'})
        if created:
            merch.set_password('merchant123')
            merch.save()

        if reset:
            Order.objects.all().delete()

        for i, (po, desc, style, ship) in enumerate(ORDERS):
            order = Order.objects.create(po_number=po, buyer='N&I', factory='Afrah', ship_date=ship, created_by=admin)
            line = OrderLine.objects.create(order=order, style=style, description=desc, qty=14040,
                                            unit_price=Decimal('4.60'))
            if i == 0:
                self.build_full_order(order, line)

        self.stdout.write(self.style.SUCCESS(
            'Demo loaded. Log in as admin / admin123 (sees costing) or merchant / merchant123 (no prices).'))

    def build_full_order(self, order, line):
        line.size_type = 'letter'
        line.save()
        for pos, color in enumerate(COLORS):
            AssortmentRow.objects.create(line=line, color=color, position=pos, qtys=ASSORTMENT[color] + [0] * 4)

        for pos, (name, placement, supplier, unit, alloc, cons, combo, spec, price) in enumerate(BOM):
            category = next(cat for cat, upto in CATEGORY_UPTO if pos < upto)
            item = BOMItem.objects.create(
                line=line, category=category, name=name, placement=placement, supplier=supplier, unit=unit, allocation=alloc,
                consumption=Decimal(cons), color_combo=combo if isinstance(combo, str) else '',
                spec=spec if isinstance(spec, str) else '', position=pos,
            )
            item.sync_rows()
            for row in item.rows.all():
                if isinstance(combo, dict):
                    row.color_combo = combo[row.body_color]
                if isinstance(spec, list):
                    row.spec = spec[row.size_idx]
                row.price = Decimal(price)
                row.save()
        for name, cost in EXTRAS:
            CostExtra.objects.create(line=line, name=name, cost_per_pc=Decimal(cost))

        order.stage = Order.STAGE_PO
        order.save()

        generate_supplier_pos(order)
        SupplierPO.objects.filter(order=order, supplier='Roundstone').update(
            status='issued', pi_no='RS-PI-2611', etd=datetime.date(2026, 11, 20), eta=datetime.date(2026, 11, 28))

