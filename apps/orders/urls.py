from django.urls import path

from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('orders/new/', views.order_create, name='order_create'),
    path('orders/<int:pk>/', views.order_detail, name='order_detail'),
    path('orders/<int:pk>/update/', views.order_update, name='order_update'),
    path('orders/<int:pk>/delete/', views.order_delete, name='order_delete'),
    path('orders/<int:pk>/advance/<int:stage>/', views.advance, name='advance'),

    path('orders/<int:pk>/lines/add/', views.line_add, name='line_add'),
    path('orders/<int:pk>/lines/<int:line_id>/update/', views.line_update, name='line_update'),
    path('orders/<int:pk>/lines/<int:line_id>/delete/', views.line_delete, name='line_delete'),

    path('orders/<int:pk>/lines/<int:line_id>/assortment/', views.assortment_save, name='assortment_save'),

    path('orders/<int:pk>/lines/<int:line_id>/bom/add/', views.bom_item_add, name='bom_item_add'),
    path('orders/<int:pk>/lines/<int:line_id>/bom/save/', views.bom_save, name='bom_save'),
    path('orders/<int:pk>/bom/<int:item_id>/delete/', views.bom_item_delete, name='bom_item_delete'),

    path('orders/<int:pk>/lines/<int:line_id>/costing/', views.costing_save, name='costing_save'),
    path('orders/<int:pk>/lines/<int:line_id>/costing/extra/', views.extra_add, name='extra_add'),
    path('orders/<int:pk>/costing/extra/<int:extra_id>/delete/', views.extra_delete, name='extra_delete'),

    path('orders/<int:pk>/po/generate/', views.po_generate, name='po_generate'),
    path('orders/<int:pk>/po/<int:po_id>/update/', views.po_update, name='po_update'),
    path('orders/<int:pk>/po/<int:po_id>/lines/', views.po_lines_save, name='po_lines_save'),
    path('orders/<int:pk>/po/<int:po_id>/delete/', views.po_delete, name='po_delete'),

    path('supplier-po/', views.po_list, name='po_list'),
    path('supplier-po/<int:po_id>/print/', views.po_print, name='po_print'),
]
