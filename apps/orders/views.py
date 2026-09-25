from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .forms import BOMItemForm, CostExtraForm, OrderForm, OrderLineForm, SupplierPOForm
from .models import SIZE_COUNT, ZERO, AssortmentRow, BOMItem, BOMRow, CostExtra, Order, OrderLine, SupplierPO
from .services import generate_supplier_pos, line_costing, load_bom, unassigned_rows

# (key, label, stage that unlocks it, icon)
TABS = [
    ('order', 'Order', Order.STAGE_ORDER, 'bi-clipboard'),
    ('lines', 'Line Items', Order.STAGE_LINES, 'bi-list-ul'),
    ('assortment', 'Assortment', Order.STAGE_ASSORTMENT, 'bi-grid-3x3'),
    ('bom', 'BOM', Order.STAGE_BOM, 'bi-diagram-3'),
    ('costing', 'Costing', Order.STAGE_COSTING, 'bi-calculator'),
    ('po', 'Supplier PO', Order.STAGE_PO, 'bi-truck'),
]
TAB_STAGE = {key: stage for key, _, stage, _ in TABS}

DEFAULT_UNITS = ['Pcs', 'Yds', 'Mtr', 'Gross', 'Cone', 'Kg', 'Roll', 'Set', 'Dozen']
DEFAULT_COST_HEADS = ['CM', 'Washing', 'Embellishment', 'Testing', 'Commercial', 'Freight', 'Profit']


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def is_admin(user):
    return user.is_staff or user.is_superuser


def require_admin(user):
    if not is_admin(user):
        raise PermissionDenied('Only admins can see or enter prices.')


def to_dec(value, default=None):
    value = (value or '').strip().replace(',', '')
    if not value:
        return default
    try:
        return Decimal(value)
    except InvalidOperation:
        return default


def to_int(value, default=0):
    value = (value or '').strip().replace(',', '')
    try:
        return max(int(Decimal(value)), 0) if value else default
    except InvalidOperation:
        return default


def order_url(order, tab, line=None):
    url = reverse('order_detail', args=[order.pk]) + f'?tab={tab}'
    if line is not None:
        url += f'&line={line.pk}'
    return url


def tab_unlocked(order, key, user):
    if key == 'costing' and not is_admin(user):
        return False
    return order.stage >= TAB_STAGE[key]


def tab_states(order, user):
    return [
        {'key': key, 'label': label, 'num': i + 1, 'icon': icon,
         'unlocked': tab_unlocked(order, key, user), 'done': order.stage > stage,
         'admin_only': key == 'costing'}
        for i, (key, label, stage, icon) in enumerate(TABS)
    ]


def distinct(qs, field):
    return sorted({v.strip() for v in qs.values_list(field, flat=True) if v and v.strip()}, key=str.lower)


def suggestions():
    """Values for the free-text fields' autocomplete lists."""
    return {
        'buyers': distinct(Order.objects, 'buyer'),
        'factories': distinct(Order.objects, 'factory'),
        'suppliers': sorted(set(distinct(BOMItem.objects, 'supplier')) | set(distinct(SupplierPO.objects, 'supplier')),
                            key=str.lower),
        'materials': distinct(BOMItem.objects, 'name'),
        'placements': distinct(BOMItem.objects, 'placement'),
        'units': sorted(set(DEFAULT_UNITS) | set(distinct(BOMItem.objects, 'unit')), key=str.lower),
        'cost_heads': sorted(set(DEFAULT_COST_HEADS) | set(distinct(CostExtra.objects, 'name')), key=str.lower),
        'colors': distinct(AssortmentRow.objects, 'color'),
    }


# --------------------------------------------------------------------------
# pages
# --------------------------------------------------------------------------

@login_required
def home(request):
    status = request.GET.get('status', 'running')
    q = request.GET.get('q', '').strip()

    orders = Order.objects.prefetch_related('lines')
    if status in dict(Order.STATUS_CHOICES):
        orders = orders.filter(status=status)
    if q:
        orders = orders.filter(
            Q(po_number__icontains=q) | Q(buyer__icontains=q) | Q(factory__icontains=q)
            | Q(lines__style__icontains=q) | Q(lines__description__icontains=q)
        ).distinct()

    running = list(Order.objects.filter(status='running').prefetch_related('lines'))
    kpis = {
        'count': len(running),
        'qty': sum(o.total_qty for o in running),
        'value': sum((o.total_amount for o in running), ZERO),
        'due_soon': sum(1 for o in running if o.ship_status == 'amber'),
        'overdue': sum(1 for o in running if o.ship_status == 'red'),
    }
    return render(request, 'orders/home.html', {
        'orders': orders, 'status': status, 'q': q, 'kpis': kpis,
        'stage_labels': [label for _, label, _, _ in TABS],
        'status_choices': Order.STATUS_CHOICES,
    })


@login_required
def order_create(request):
    form = OrderForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        order = form.save(commit=False)
        order.created_by = request.user
        order.stage = Order.STAGE_LINES
        order.save()
        messages.success(request, f'{order.order_no} created. Now add its line items.')
        return redirect(order_url(order, 'lines'))
    return render(request, 'orders/order_new.html', {'form': form, 'sg': suggestions()})


@login_required
def order_detail(request, pk):
    order = get_object_or_404(Order, pk=pk)
    user = request.user
    admin = is_admin(user)

    tab = request.GET.get('tab')
    if tab not in TAB_STAGE or not tab_unlocked(order, tab, user):
        # Land on the furthest tab this user may open.
        tab = next(k for k, _, s, _ in reversed(TABS) if tab_unlocked(order, k, user))

    lines = list(order.lines.prefetch_related('assortment'))
    line = None
    if lines:
        line_id = request.GET.get('line')
        line = next((ln for ln in lines if str(ln.pk) == line_id), lines[0])

    ctx = {
        'order': order, 'tab': tab, 'tabs': tab_states(order, user), 'lines': lines, 'line': line,
        'is_admin': admin, 'sg': suggestions(), 'size_count': range(SIZE_COUNT),
    }

    if tab == 'order':
        ctx['form'] = OrderForm(instance=order)
    elif tab == 'lines':
        ctx['new_line_form'] = OrderLineForm()
        ctx['line_forms'] = [(ln, OrderLineForm(instance=ln, prefix=f'ln{ln.pk}')) for ln in lines]
        ctx['can_continue'] = bool(lines)
    elif tab == 'assortment' and line:
        rows = list(line.assortment.all())
        ctx.update({
            'rows': rows,
            'col_totals': [line.size_total(i) for i in range(SIZE_COUNT)],
            'grand_total': line.assortment_total,
            'diff': line.assortment_total - line.qty,
            'size_types': OrderLine.SIZE_TYPE_CHOICES,
            'can_continue': all(ln.assortment_complete for ln in lines),
            'size_sets': {'letter': OrderLine(size_type='letter').sizes, 'number': OrderLine(size_type='number').sizes},
        })
    elif tab in ('bom', 'costing') and line:
        items = load_bom(line)
        ctx['items'] = items
        if tab == 'bom':
            ctx['new_item_form'] = BOMItemForm()
            ctx['allocations'] = BOMItem.ALLOCATION_CHOICES
            ctx['lines_without_bom'] = [ln for ln in lines if not ln.bom_items.exists()]
            ctx['can_continue'] = not ctx['lines_without_bom']
        else:
            ctx['costing'] = line_costing(line, items)
            ctx['all_costing'] = [line_costing(ln) for ln in lines]
            ctx['can_continue'] = all(c['row_count'] and not c['unpriced'] for c in ctx['all_costing'])
    elif tab == 'po':
        pos = list(order.supplier_pos.prefetch_related('lines'))
        ctx['pos'] = [(po, SupplierPOForm(instance=po, prefix=f'po{po.pk}')) for po in pos]
        groups = unassigned_rows(order)
        ctx['pending'] = [
            {'supplier': s or '— no supplier —', 'has_supplier': bool(s), 'rows': rows,
             'items': sorted({r.item.name for r in rows})}
            for s, rows in groups.items()
        ]
        ctx['can_generate'] = any(g['has_supplier'] for g in ctx['pending'])

    return render(request, 'orders/detail.html', ctx)


@login_required
def po_list(request):
    q = request.GET.get('q', '').strip()
    pos = SupplierPO.objects.select_related('order').prefetch_related('lines')
    if q:
        pos = pos.filter(Q(supplier__icontains=q) | Q(order__po_number__icontains=q)
                         | Q(pi_no__icontains=q) | Q(lc_no__icontains=q))
    return render(request, 'orders/po_list.html', {'pos': pos, 'q': q, 'is_admin': is_admin(request.user)})


@login_required
def po_print(request, po_id):
    po = get_object_or_404(SupplierPO.objects.select_related('order'), pk=po_id)
    return render(request, 'orders/po_print.html', {'po': po, 'is_admin': is_admin(request.user)})


# --------------------------------------------------------------------------
# tab 1 — order
# --------------------------------------------------------------------------

@login_required
@require_POST
def order_update(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = OrderForm(request.POST, instance=order)
    if form.is_valid():
        form.save()
        messages.success(request, 'Order saved.')
    else:
        messages.error(request, 'Order not saved: ' + '; '.join(
            f'{field}: {", ".join(errs)}' for field, errs in form.errors.items()))
    return redirect(order_url(order, 'order'))


@login_required
@require_POST
def order_delete(request, pk):
    require_admin(request.user)
    order = get_object_or_404(Order, pk=pk)
    order.delete()
    messages.success(request, f'{order.po_number} deleted.')
    return redirect('home')


@login_required
@require_POST
def advance(request, pk, stage):
    """'Save & continue' — unlock the next tab once the current one is complete."""
    order = get_object_or_404(Order, pk=pk)
    lines = list(order.lines.prefetch_related('assortment'))
    problem = None
    if stage == Order.STAGE_ASSORTMENT and not lines:
        problem = 'Add at least one line item first.'
    elif stage == Order.STAGE_BOM:
        bad = [ln.style for ln in lines if not ln.assortment_complete]
        if bad:
            problem = 'Assortment total must match line qty for: ' + ', '.join(bad)
    elif stage == Order.STAGE_COSTING:
        bad = [ln.style for ln in lines if not ln.bom_items.exists()]
        if bad:
            problem = 'Add BOM materials for: ' + ', '.join(bad)
    elif stage == Order.STAGE_PO:
        require_admin(request.user)
        bad = [c['line'].style for c in (line_costing(ln) for ln in lines) if c['unpriced'] or not c['row_count']]
        if bad:
            problem = 'Enter a price for every BOM row of: ' + ', '.join(bad)
    elif stage not in TAB_STAGE.values():
        problem = 'Unknown step.'

    if problem:
        messages.error(request, problem)
        back = next(k for k, _, s, _ in TABS if s == stage - 1)
        return redirect(order_url(order, back))

    order.advance_to(stage)
    next_tab = next(k for k, _, s, _ in TABS if s == stage)
    if next_tab == 'costing' and not is_admin(request.user):
        messages.info(request, 'BOM complete. Costing is now waiting for an admin to enter prices.')
        return redirect(order_url(order, 'bom'))
    messages.success(request, f'Step complete — {dict((k, lbl) for k, lbl, _, _ in TABS)[next_tab]} unlocked.')
    return redirect(order_url(order, next_tab))


# --------------------------------------------------------------------------
# tab 2 — line items
# --------------------------------------------------------------------------

@login_required
@require_POST
def line_add(request, pk):
    order = get_object_or_404(Order, pk=pk)
    form = OrderLineForm(request.POST)
    if form.is_valid():
        line = form.save(commit=False)
        line.order = order
        line.save()
        messages.success(request, f'Line {line.style} added.')
    else:
        messages.error(request, 'Line not added — style, qty and price are required.')
    return redirect(order_url(order, 'lines'))


@login_required
@require_POST
def line_update(request, pk, line_id):
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    form = OrderLineForm(request.POST, instance=line, prefix=f'ln{line.pk}')
    if form.is_valid():
        form.save()
        messages.success(request, f'Line {line.style} saved.')
    else:
        messages.error(request, 'Line not saved — check qty and price.')
    return redirect(order_url(line.order, 'lines'))


@login_required
@require_POST
def line_delete(request, pk, line_id):
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    line.delete()
    messages.success(request, f'Line {line.style} deleted.')
    return redirect(order_url(line.order, 'lines'))


# --------------------------------------------------------------------------
# tab 3 — assortment
# --------------------------------------------------------------------------

@login_required
@require_POST
def assortment_save(request, pk, line_id):
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    post = request.POST
    size_type = post.get('size_type', '')
    if size_type not in dict(OrderLine.SIZE_TYPE_CHOICES):
        messages.error(request, 'Choose a size type: letter sizes or number sizes.')
        return redirect(order_url(line.order, 'assortment', line))

    indexes = sorted(int(k.split('-')[1]) for k in post if k.startswith('color-') and k.split('-')[1].isdigit())
    new_rows, seen = [], set()
    for n in indexes:
        color = post.get(f'color-{n}', '').strip()
        qtys = [to_int(post.get(f'q-{n}-{j}')) for j in range(SIZE_COUNT)]
        if not color and not any(qtys):
            continue
        if not color:
            messages.error(request, 'Every row with quantities needs a color name.')
            return redirect(order_url(line.order, 'assortment', line))
        if color.lower() in seen:
            messages.error(request, f'Color "{color}" is entered twice.')
            return redirect(order_url(line.order, 'assortment', line))
        seen.add(color.lower())
        new_rows.append(AssortmentRow(line=line, color=color, qtys=qtys, position=len(new_rows)))

    with transaction.atomic():
        line.size_type = size_type
        line.save(update_fields=['size_type'])
        line.assortment.all().delete()
        AssortmentRow.objects.bulk_create(new_rows)
        for item in line.bom_items.all():
            item.sync_rows()

    line = OrderLine.objects.get(pk=line.pk)
    if line.assortment_total == line.qty:
        messages.success(request, f'Assortment for {line.style} saved — total matches {line.qty:,} pcs.')
    else:
        messages.warning(request, f'Assortment saved, but total {line.assortment_total:,} ≠ line qty {line.qty:,}.')
    return redirect(order_url(line.order, 'assortment', line))


# --------------------------------------------------------------------------
# tab 4 — BOM (material allocation)
# --------------------------------------------------------------------------

def cons_from_req(req, qty):
    """Consumption / pc that gives `req` in total for `qty` pieces."""
    return req / qty if qty else ZERO


@login_required
@require_POST
def bom_item_add(request, pk, line_id):
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    form = BOMItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.line = line
        item.position = (line.bom_items.aggregate(m=Max('position'))['m'] or 0) + 1
        item.save()
        item.sync_rows()
        total_req = form.cleaned_data.get('total_req')
        if total_req:
            # Spread the typed total over the rows at one consumption / pc.
            rows = list(item.rows.all())
            item.consumption = cons_from_req(total_req, sum(r.order_qty for r in rows))
            item.save(update_fields=['consumption'])
            for row in rows:
                row.consumption = item.consumption
                row.save(update_fields=['consumption'])
        messages.success(request, f'{item.name} added with {item.rows.count()} row(s).')
    else:
        messages.error(request, 'Material not added: ' + '; '.join(
            f'{form.fields[f].label if f in form.fields else f}: {", ".join(e)}' for f, e in form.errors.items()))
    return redirect(order_url(line.order, 'bom', line))


@login_required
@require_POST
def bom_item_delete(request, pk, item_id):
    item = get_object_or_404(BOMItem.objects.select_related('line__order'), pk=item_id, line__order_id=pk)
    item.delete()
    messages.success(request, f'{item.name} removed from BOM.')
    return redirect(order_url(item.line.order, 'bom', item.line))


@login_required
@require_POST
def bom_save(request, pk, line_id):
    """Saves a style's whole BOM sheet — material cells and row cells — in one
    go. Per row, whichever of consumption / total req. was typed last wins
    (`src`) and the other is derived from it; untouched rows keep their
    stored consumption at full precision."""
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    post = request.POST
    allocations = dict(BOMItem.ALLOCATION_CHOICES)
    with transaction.atomic():
        for item in line.bom_items.all():
            key = f'i-{item.pk}-'
            if key + 'name' not in post:
                continue
            old_allocation = item.allocation
            item.name = post.get(key + 'name', '').strip() or item.name
            item.placement = post.get(key + 'placement', '').strip()
            item.unit = post.get(key + 'unit', '').strip()
            item.supplier = post.get(key + 'supplier', '').strip()
            if post.get(key + 'allocation') in allocations:
                item.allocation = post[key + 'allocation']
            item.save()
            if item.allocation != old_allocation:
                item.sync_rows()
        line = OrderLine.objects.get(pk=line.pk)
        for row in BOMRow.objects.filter(item__line=line).select_related('item'):
            key = f'r-{row.pk}-'
            if key + 'cons' not in post:
                continue
            row.item.line = line
            row.color_combo = post.get(key + 'combo', row.color_combo).strip()
            row.spec = post.get(key + 'spec', row.spec).strip()
            qty = post.get(key + 'qty', '').strip()
            row.qty_override = to_int(qty) if qty else None
            src = post.get(key + 'src')
            if src == 'req':
                row.consumption = cons_from_req(to_dec(post.get(key + 'req'), ZERO), row.order_qty)
            elif src == 'cons':
                row.consumption = to_dec(post.get(key + 'cons'), ZERO)
            row.save()
    messages.success(request, 'BOM saved.')
    return redirect(order_url(line.order, 'bom', line))


# --------------------------------------------------------------------------
# tab 5 — costing (admin only)
# --------------------------------------------------------------------------

@login_required
@require_POST
def costing_save(request, pk, line_id):
    require_admin(request.user)
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    for row in BOMRow.objects.filter(item__line=line):
        field = f'r-{row.pk}-price'
        if field in request.POST:
            row.price = to_dec(request.POST[field])
            row.save(update_fields=['price'])
    messages.success(request, f'Prices for {line.style} saved.')
    return redirect(order_url(line.order, 'costing', line))


@login_required
@require_POST
def extra_add(request, pk, line_id):
    require_admin(request.user)
    line = get_object_or_404(OrderLine, pk=line_id, order_id=pk)
    form = CostExtraForm(request.POST)
    if form.is_valid():
        extra = form.save(commit=False)
        extra.line = line
        extra.save()
    else:
        messages.error(request, 'Cost head needs a name and a cost per piece.')
    return redirect(order_url(line.order, 'costing', line))


@login_required
@require_POST
def extra_delete(request, pk, extra_id):
    require_admin(request.user)
    extra = get_object_or_404(CostExtra.objects.select_related('line__order'), pk=extra_id, line__order_id=pk)
    extra.delete()
    return redirect(order_url(extra.line.order, 'costing', extra.line))


# --------------------------------------------------------------------------
# tab 6 — supplier PO
# --------------------------------------------------------------------------

@login_required
@require_POST
def po_generate(request, pk):
    order = get_object_or_404(Order, pk=pk)
    if order.stage < Order.STAGE_PO:
        raise PermissionDenied
    created = generate_supplier_pos(order)
    if created:
        messages.success(request, f'{len(created)} supplier PO(s) created: ' + ', '.join(p.supplier for p in created))
    else:
        messages.info(request, 'Nothing to generate — every material with a supplier is already on a PO.')
    return redirect(order_url(order, 'po'))


@login_required
@require_POST
def po_update(request, pk, po_id):
    po = get_object_or_404(SupplierPO, pk=po_id, order_id=pk)
    form = SupplierPOForm(request.POST, instance=po, prefix=f'po{po.pk}')
    if form.is_valid():
        form.save()
        messages.success(request, f'{po.po_no} saved.')
    else:
        messages.error(request, f'{po.po_no} not saved — check the dates.')
    return redirect(order_url(po.order, 'po'))


@login_required
@require_POST
def po_lines_save(request, pk, po_id):
    po = get_object_or_404(SupplierPO, pk=po_id, order_id=pk)
    admin = is_admin(request.user)
    for line in po.lines.all():
        qty = to_dec(request.POST.get(f'l-{line.pk}-qty'))
        if qty is not None:
            line.qty = qty
        if admin and f'l-{line.pk}-price' in request.POST:
            line.price = to_dec(request.POST[f'l-{line.pk}-price'])
        line.save()
    messages.success(request, f'{po.po_no} quantities saved.')
    return redirect(order_url(po.order, 'po'))


@login_required
@require_POST
def po_delete(request, pk, po_id):
    po = get_object_or_404(SupplierPO, pk=po_id, order_id=pk)
    po_no = po.po_no
    po.delete()
    messages.success(request, f'{po_no} deleted — its materials can be generated again.')
    return redirect(order_url(po.order, 'po'))
