from django import forms

from .models import BOMItem, CostExtra, Order, OrderLine, SupplierPO


class BootstrapMixin:
    """Gives every widget Bootstrap classes so templates can render fields plainly."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.Select):
                widget.attrs.setdefault('class', 'form-select')
            elif not isinstance(widget, (forms.CheckboxInput, forms.RadioSelect)):
                widget.attrs.setdefault('class', 'form-control')


class DateInput(forms.DateInput):
    input_type = 'date'

    def __init__(self, attrs=None):
        super().__init__(attrs, format='%Y-%m-%d')


class OrderForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = Order
        fields = ['po_number', 'buyer', 'factory', 'ship_date', 'currency', 'status', 'remarks']
        widgets = {
            'ship_date': DateInput(),
            'remarks': forms.Textarea(attrs={'rows': 2}),
            'buyer': forms.TextInput(attrs={'list': 'dl-buyers', 'autocomplete': 'off'}),
            'factory': forms.TextInput(attrs={'list': 'dl-factories', 'autocomplete': 'off'}),
        }


class OrderLineForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = OrderLine
        fields = ['style', 'description', 'qty', 'unit_price']
        widgets = {'unit_price': forms.NumberInput(attrs={'step': '0.0001'})}


class BOMItemForm(BootstrapMixin, forms.ModelForm):
    """The one-line 'add material' row at the bottom of a style's BOM sheet.
    Type either consumption / pc or the total requirement."""

    total_req = forms.DecimalField(label='Total req.', required=False, min_value=0,
                                   widget=forms.NumberInput(attrs={'step': 'any', 'placeholder': 'or total'}))

    class Meta:
        model = BOMItem
        fields = ['category', 'name', 'placement', 'allocation', 'color_combo', 'spec', 'consumption', 'unit']
        widgets = {
            'name': forms.TextInput(attrs={'list': 'dl-materials', 'autocomplete': 'off'}),
            'placement': forms.TextInput(attrs={'list': 'dl-placements', 'autocomplete': 'off'}),
            'unit': forms.TextInput(attrs={'list': 'dl-units', 'autocomplete': 'off'}),
            'color_combo': forms.TextInput(attrs={'list': 'dl-colors', 'autocomplete': 'off',
                                                  'placeholder': 'Body color'}),
            'consumption': forms.NumberInput(attrs={'step': 'any', 'min': '0', 'placeholder': 'per pc'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['consumption'].required = False
        for field in self.fields.values():
            # Rendered as spreadsheet cells in the BOM sheet's last row, outside the <form>.
            field.widget.attrs.update({'form': 'addForm', 'class': ''})

    def clean_consumption(self):
        return self.cleaned_data.get('consumption') or 0


class CostExtraForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = CostExtra
        fields = ['name', 'cost_per_pc']
        widgets = {
            'name': forms.TextInput(attrs={'list': 'dl-cost-heads', 'placeholder': 'e.g. CM, Washing, Commercial'}),
            'cost_per_pc': forms.NumberInput(attrs={'step': 'any'}),
        }


class SupplierPOForm(BootstrapMixin, forms.ModelForm):
    class Meta:
        model = SupplierPO
        fields = ['supplier', 'material_type', 'po_date', 'delivery_date', 'status', 'pi_no', 'lc_no', 'etd', 'eta',
                  'notes']
        widgets = {
            'po_date': DateInput(), 'delivery_date': DateInput(), 'etd': DateInput(), 'eta': DateInput(),
            'notes': forms.Textarea(attrs={'rows': 2}),
            'supplier': forms.TextInput(attrs={'list': 'dl-suppliers', 'autocomplete': 'off'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['material_type'].choices = [('', 'Mixed')] + list(self.fields['material_type'].choices)[1:]
