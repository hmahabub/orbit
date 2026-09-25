from django.contrib import admin

from .models import AssortmentRow, BOMItem, BOMRow, CostExtra, Order, OrderLine, SupplierPO, SupplierPOLine


class OrderLineInline(admin.TabularInline):
    model = OrderLine
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ['order_no', 'po_number', 'buyer', 'factory', 'ship_date', 'status', 'stage']
    list_filter = ['status', 'buyer']
    search_fields = ['po_number', 'buyer', 'factory']
    inlines = [OrderLineInline]


class AssortmentInline(admin.TabularInline):
    model = AssortmentRow
    extra = 0


@admin.register(OrderLine)
class OrderLineAdmin(admin.ModelAdmin):
    list_display = ['style', 'description', 'order', 'qty', 'unit_price', 'size_type']
    inlines = [AssortmentInline]


class BOMRowInline(admin.TabularInline):
    model = BOMRow
    extra = 0


@admin.register(BOMItem)
class BOMItemAdmin(admin.ModelAdmin):
    list_display = ['name', 'line', 'placement', 'supplier', 'unit', 'allocation', 'consumption']
    search_fields = ['name', 'supplier']
    inlines = [BOMRowInline]


class SupplierPOLineInline(admin.TabularInline):
    model = SupplierPOLine
    extra = 0
    exclude = ['bom_rows']


@admin.register(SupplierPO)
class SupplierPOAdmin(admin.ModelAdmin):
    list_display = ['po_no', 'supplier', 'order', 'po_date', 'status']
    list_filter = ['status']
    search_fields = ['supplier', 'pi_no', 'lc_no']
    inlines = [SupplierPOLineInline]


admin.site.register(CostExtra)
