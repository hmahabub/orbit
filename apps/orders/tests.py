from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import BOMItem, BOMRow, Order, SupplierPO


class WorkflowTests(TestCase):
    """Walks one order through all six tabs as a merchandiser and an admin."""

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user('boss', password='x', is_staff=True)
        self.merch = User.objects.create_user('merch', password='x')
        self.client.force_login(self.merch)

    def detail(self, order, tab, **extra):
        params = {'tab': tab, **extra}
        return self.client.get(reverse('order_detail', args=[order.pk]), params)

    def create_order(self):
        self.client.post(reverse('order_create'), {
            'po_number': 'WC6916', 'buyer': 'N&I', 'factory': 'Afrah', 'ship_date': '2026-12-30',
            'currency': 'USD', 'status': 'running'})
        return Order.objects.get(po_number='WC6916')

    def add_line_and_assortment(self, order):
        self.client.post(reverse('line_add', args=[order.pk]), {
            'style': 'WC217G398', 'description': 'TRAVIS ZIP CARGO PANT', 'qty': 14040, 'unit_price': '4.60'})
        line = order.lines.get()
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_ASSORTMENT]))
        data = {'size_type': 'letter'}
        for n, (color, qtys) in enumerate([('OYSTER', [836, 1672, 1672, 836]), ('STEEL', [668, 1336, 1336, 668]),
                                           ('FERN CAMO', [836, 1672, 1672, 836])]):
            data[f'color-{n}'] = color
            for j, q in enumerate(qtys):
                data[f'q-{n}-{j}'] = q
        self.client.post(reverse('assortment_save', args=[order.pk, line.pk]), data)
        return order.lines.get()

    def test_tabs_unlock_in_order(self):
        order = self.create_order()
        self.assertEqual(order.stage, Order.STAGE_LINES)
        # Assortment is locked until a line exists and the step is completed.
        self.assertEqual(self.detail(order, 'assortment').context['tab'], 'lines')
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_ASSORTMENT]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_LINES)

        line = self.add_line_and_assortment(order)
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_ASSORTMENT)
        self.assertTrue(line.assortment_complete)

        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_BOM]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_BOM)

        # BOM can't be completed empty.
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_COSTING]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_BOM)

    def test_assortment_mismatch_blocks_bom(self):
        order = self.create_order()
        self.client.post(reverse('line_add', args=[order.pk]), {
            'style': 'S1', 'description': '', 'qty': 100, 'unit_price': '1'})
        line = order.lines.get()
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_ASSORTMENT]))
        self.client.post(reverse('assortment_save', args=[order.pk, line.pk]),
                         {'size_type': 'number', 'color-0': 'RED', 'q-0-0': 60})
        line.refresh_from_db()
        self.assertEqual(line.sizes[0], '30')
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_BOM]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_ASSORTMENT)

    def add_material(self, line, **fields):
        data = {'category': 'trims', 'placement': '', 'unit': 'Pcs', 'allocation': 'all',
                'consumption': '1', 'color_combo': '', 'spec': '', **fields}
        self.client.post(reverse('bom_item_add', args=[line.order_id, line.pk]), data)
        return BOMItem.objects.get(line=line, name=fields['name'])

    def test_bom_allocation_and_requirement_match_spreadsheet(self):
        order = self.create_order()
        line = self.add_line_and_assortment(order)
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_BOM]))
        twill = self.add_material(line, name='Twill', allocation='color', consumption='1.478070', spec='58"',
                                  category='fabric', unit='Yds')
        cord = self.add_material(line, name='Drawcord', allocation='size', color_combo='Black')
        self.add_material(line, name='Grommet', consumption='2')

        oyster = twill.rows.get(body_color='OYSTER')
        self.assertEqual(oyster.order_qty, 5016)
        self.assertEqual(oyster.color_combo, 'OYSTER')
        self.assertAlmostEqual(float(oyster.requirement), 7414.0, places=0)   # =G10/12*H10
        self.assertEqual([r.size_label for r in cord.rows.all()], ['S', 'M', 'L', 'XL'])
        self.assertEqual(cord.rows.get(size_idx=1).order_qty, 4680)
        grommet = BOMItem.objects.get(name='Grommet').rows.get()
        self.assertEqual(grommet.requirement, 14040 * 2)   # always per piece, no wastage

        # One save covers item cells and row cells; qty override; switching allocation rebuilds rows.
        self.client.post(reverse('bom_save', args=[order.pk, line.pk]), {
            f'i-{twill.pk}-name': 'Twill', f'i-{twill.pk}-allocation': 'color',
            f'i-{twill.pk}-unit': 'Yds', f'i-{twill.pk}-category': 'fabric', f'i-{twill.pk}-placement': 'Body',
            f'i-{cord.pk}-name': 'Drawcord', f'i-{cord.pk}-allocation': 'all',
            f'r-{oyster.pk}-cons': '1.478070', f'r-{oyster.pk}-qty': '5000', f'r-{oyster.pk}-src': '',
            f'r-{oyster.pk}-combo': 'OYSTER', f'r-{oyster.pk}-spec': '58"'})
        self.assertEqual(BOMRow.objects.get(pk=oyster.pk).order_qty, 5000)
        self.assertEqual(BOMItem.objects.get(pk=twill.pk).placement, 'Body')
        self.assertEqual(cord.rows.count(), 1)

        # Assortment change re-syncs rows but keeps what was typed.
        self.client.post(reverse('assortment_save', args=[order.pk, line.pk]),
                         {'size_type': 'letter', 'color-0': 'OYSTER', 'q-0-0': 14040})
        self.assertEqual(twill.rows.count(), 1)
        self.assertEqual(BOMRow.objects.get(pk=oyster.pk).consumption, Decimal('1.478070'))

    def test_total_requirement_drives_consumption(self):
        order = self.create_order()
        line = self.add_line_and_assortment(order)
        # Add row: a typed total is spread over the rows at one consumption / pc.
        fabric = self.add_material(line, name='Fabric', allocation='color', consumption='', total_req='20752')
        steel = fabric.rows.get(body_color='STEEL')
        self.assertAlmostEqual(float(steel.consumption), 20752 / 14040, places=8)
        self.assertAlmostEqual(float(sum(r.requirement for r in fabric.rows.all())), 20752, places=4)

        # Sheet: typing Total req. on a row sets its consumption = req / qty.
        oyster = fabric.rows.get(body_color='OYSTER')
        post = {f'i-{fabric.pk}-name': 'Fabric', f'i-{fabric.pk}-allocation': 'color'}
        for r in fabric.rows.all():
            post.update({f'r-{r.pk}-cons': '9', f'r-{r.pk}-req': '1', f'r-{r.pk}-qty': '', f'r-{r.pk}-src': '',
                         f'r-{r.pk}-combo': r.color_combo, f'r-{r.pk}-spec': ''})
        post.update({f'r-{oyster.pk}-req': '7414', f'r-{oyster.pk}-src': 'req',
                     f'r-{steel.pk}-cons': '1.5', f'r-{steel.pk}-src': 'cons'})
        self.client.post(reverse('bom_save', args=[order.pk, line.pk]), post)
        oyster.refresh_from_db()
        self.assertAlmostEqual(float(oyster.requirement), 7414, places=4)
        self.assertAlmostEqual(float(oyster.consumption), 7414 / 5016, places=8)
        self.assertEqual(BOMRow.objects.get(pk=steel.pk).consumption, Decimal('1.5'))
        # Untouched row keeps its stored consumption (src empty ignores the posted '9').
        camo = fabric.rows.get(body_color='FERN CAMO')
        self.assertAlmostEqual(float(camo.consumption), 20752 / 14040, places=8)

    def test_costing_is_admin_only_and_pos_generate(self):
        order = self.create_order()
        self.add_line_and_assortment(order)
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_BOM]))
        line = order.lines.get()
        twill = self.add_material(line, name='Twill', category='fabric', unit='Yds', allocation='color',
                                  consumption='1.478070')
        zipper = self.add_material(line, name='Zipper', category='trims')
        label = self.add_material(line, name='Care label', category='labels')
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_COSTING]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_COSTING)

        # Merchandiser: costing tab hidden, price endpoints refused, no prices in HTML.
        self.assertEqual(self.detail(order, 'costing').context['tab'], 'bom')
        self.assertEqual(self.client.post(reverse('costing_save', args=[order.pk, order.lines.get().pk])).status_code, 403)
        self.assertEqual(self.client.post(reverse('advance', args=[order.pk, Order.STAGE_PO])).status_code, 403)

        self.client.force_login(self.admin)
        self.assertEqual(self.detail(order, 'costing').context['tab'], 'costing')
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_PO]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_COSTING)  # unpriced rows block it
        prices = {f'r-{r.pk}-price': '1.85' for r in BOMRow.objects.all()}
        self.client.post(reverse('costing_save', args=[order.pk, order.lines.get().pk]), prices)
        self.client.post(reverse('advance', args=[order.pk, Order.STAGE_PO]))
        order.refresh_from_db()
        self.assertEqual(order.stage, Order.STAGE_PO)

        # Suppliers are chosen on the PO tab; one PO per supplier and material type.
        assign = reverse('po_assign', args=[order.pk])
        all_po_ids = lambda: list(SupplierPO.objects.values_list('pk', flat=True))  # noqa: E731
        pending = lambda: [i.name for i in self.detail(order, 'po').context['pending']]  # noqa: E731
        self.client.post(assign, {f's-{twill.pk}': 'Roundstone', f's-{zipper.pk}': 'Roundstone',
                                  f's-{label.pk}': '', 'action': 'generate'})
        self.assertEqual(sorted(SupplierPO.objects.values_list('supplier', 'material_type')),
                         [('Roundstone', 'fabric'), ('Roundstone', 'trims')])
        po = SupplierPO.objects.get(material_type='fabric')
        trims_po = SupplierPO.objects.get(material_type='trims')
        self.assertEqual(po.lines.count(), 3)
        self.assertEqual(po.lines.get(color='OYSTER').qty, 7414)
        # The label had no supplier, so it is still waiting; a second run adds nothing.
        self.assertEqual(pending(), ['Care label'])
        self.client.post(assign, {'action': 'generate'})
        self.assertEqual(SupplierPO.objects.count(), 2)

        # Move one fabric line onto the trims PO -> it becomes a mixed PO.
        steel = po.lines.get(color='STEEL')
        self.client.post(reverse('po_move', args=[order.pk, po.pk]), {'line': [steel.pk], 'target': trims_po.pk})
        trims_po.refresh_from_db()
        self.assertEqual((trims_po.lines.count(), trims_po.material_type, trims_po.type_label), (2, '', 'Mixed'))
        # Take a line off the PO altogether -> its material is pending again.
        self.client.post(reverse('po_move', args=[order.pk, po.pk]),
                         {'line': [po.lines.get(color='FERN CAMO').pk], 'target': 'pending'})
        self.assertEqual(pending(), ['Twill', 'Care label'])
        # Split a line into a new PO, then merge everything back into the oldest PO.
        self.client.post(reverse('po_move', args=[order.pk, trims_po.pk]), {'line': [steel.pk], 'target': 'new'})
        self.assertEqual(SupplierPO.objects.count(), 3)
        self.client.post(reverse('po_merge', args=[order.pk]), {'po': all_po_ids()})
        po = SupplierPO.objects.get()
        self.assertEqual(po.lines.count(), 3)
        # Different suppliers can't be merged.
        self.client.post(assign, {f's-{label.pk}': 'Alif', f's-{twill.pk}': 'Roundstone', 'action': 'generate'})
        before = SupplierPO.objects.count()
        self.client.post(reverse('po_merge', args=[order.pk]), {'po': all_po_ids()})
        self.assertEqual(SupplierPO.objects.count(), before)

        self.client.force_login(self.merch)
        html = self.client.get(reverse('po_print', args=[po.pk])).content.decode()
        self.assertNotIn('1.8500', html)
        self.assertIn('Roundstone', html)

    def test_pages_render(self):
        from django.core.management import call_command
        call_command('seed_demo', stdout=open('nul' if __import__('os').name == 'nt' else '/dev/null', 'w'))
        self.client.force_login(self.admin)
        order = Order.objects.get(po_number='WC6916')
        for tab in ['order', 'lines', 'assortment', 'bom', 'costing', 'po']:
            resp = self.detail(order, tab)
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.context['tab'], tab)
        for name in ['home', 'po_list', 'order_create']:
            self.assertEqual(self.client.get(reverse(name)).status_code, 200)
        self.assertEqual(self.client.get(reverse('home'), {'status': 'all', 'q': 'TRAVIS'}).status_code, 200)

    def test_reports_and_downloads(self):
        import os
        from io import BytesIO

        from django.core.management import call_command
        from openpyxl import load_workbook

        from .reports import REPORTS
        call_command('seed_demo', stdout=open(os.devnull, 'w'))

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse('report_list')).status_code, 200)
        for key in REPORTS:
            url = reverse('report_detail', args=[key])
            self.assertEqual(self.client.get(url, {'status': 'running', 'buyer': 'N&I'}).status_code, 200, key)
            self.assertIn('text/csv', self.client.get(url, {'download': 'csv'})['Content-Type'])
            wb = load_workbook(BytesIO(self.client.get(url, {'download': 'xlsx'}).content))
            self.assertGreater(wb.active.max_row, 4, key)

        table = self.client.get(reverse('report_detail', args=['orders'])).context['table']
        self.assertEqual(table.totals[-2:], [56160, Decimal('258336.00')])
        # Ship-date filter narrows the selection.
        table = self.client.get(reverse('report_detail', args=['orders']), {'ship_from': '2026-06-01'}).context['table']
        self.assertEqual([row[1] for row in table.rows], ['WC6916'])

        # Non-admins: no cost reports, no amount columns anywhere.
        self.client.force_login(self.merch)
        self.assertEqual(self.client.get(reverse('report_detail', args=['profitability'])).status_code, 403)
        denied = self.client.get(reverse('report_detail', args=['material-cost']), {'download': 'xlsx'})
        self.assertEqual(denied.status_code, 403)
        for key in ['materials', 'suppliers', 'po-register']:
            table = self.client.get(reverse('report_detail', args=[key])).context['table']
            self.assertFalse([c.label for c in table.columns if 'mount' in c.label], key)
        self.assertNotContains(self.client.get(reverse('report_list')), 'Costing &amp; margin')
