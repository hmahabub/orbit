"""BOM and costing go back to one sheet per style.

Existing 'All styles' materials and order-level cost heads are moved onto the
order's first style (dropped only if the order has no style at all).
"""

import django.db.models.deletion
from django.db import migrations, models


def move_to_first_style(apps, schema_editor):
    BOMItem = apps.get_model('orders', 'BOMItem')
    CostExtra = apps.get_model('orders', 'CostExtra')
    OrderLine = apps.get_model('orders', 'OrderLine')

    def first_line(order_id):
        return OrderLine.objects.filter(order_id=order_id).order_by('id').first()

    for item in BOMItem.objects.filter(line__isnull=True):
        line = first_line(item.order_id)
        if line is None:
            item.delete()
        else:
            item.line = line
            item.save(update_fields=['line'])
    for extra in CostExtra.objects.all():
        line = first_line(extra.order_id)
        if line is None:
            extra.delete()
        else:
            extra.line = line
            extra.save(update_fields=['line'])


class Migration(migrations.Migration):

    dependencies = [
        ('orders', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='costextra',
            name='line',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE,
                                    related_name='cost_extras', to='orders.orderline'),
        ),
        migrations.RunPython(move_to_first_style, migrations.RunPython.noop),
        migrations.RemoveField(model_name='bomitem', name='order'),
        migrations.RemoveField(model_name='costextra', name='order'),
        migrations.AlterField(
            model_name='bomitem',
            name='line',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bom_items',
                                    to='orders.orderline'),
        ),
        migrations.AlterField(
            model_name='costextra',
            name='line',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='cost_extras',
                                    to='orders.orderline'),
        ),
        migrations.AlterField(
            model_name='bomitem',
            name='consumption',
            field=models.DecimalField(decimal_places=10, default=0, max_digits=20, verbose_name='Consumption / pc'),
        ),
        migrations.AlterField(
            model_name='bomrow',
            name='consumption',
            field=models.DecimalField(decimal_places=10, default=0, max_digits=20),
        ),
    ]
