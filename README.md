# Orbit ERP

A simpler version of noorbit: one order workspace that takes a buyer order all the way to supplier POs.

```
Order → Line Items → Assortment → BOM → Costing → Supplier PO
```

The six steps are tabs on one order page. Each tab unlocks when the one before it is complete.

| Tab | What happens | Unlocks the next tab when |
|---|---|---|
| **1. Order** | Buyer PO, buyer, factory, ship date, status | Created |
| **2. Line Items** | Styles on the PO: style, description, qty, price/pc | At least one line exists |
| **3. Assortment** | Color × size breakdown per style. Pick **letter sizes** (S, M, L, XL, XXL, 3XL, 4XL, 5XL) or **number sizes** (30–44) | Every style's breakdown adds up to its line qty |
| **4. BOM** | Excel-style sheet per style: item, placement, color, size, consumption/pc ⇄ total req., supplier. **No prices** | Every style has materials |
| **5. Costing** | **Admin only.** Price per BOM row, CM/other costs, cost/pc vs FOB, margin per style | Every BOM row has a price |
| **6. Supplier PO** | One PO per supplier generated from the BOM. PI/LC/ETD/ETA, printable PO | — |

After login, users land on the list of **running orders**.

Buyer, factory, supplier and material names are typed in directly. There are no master-data modules. Fields autocomplete from values entered before.

## Who sees prices

An **admin** is a user with *staff status* (set in Django admin → Users). Only admins can:

- open the Costing tab and enter prices
- see prices and amounts on supplier POs, on screen and printed
- complete the Costing step
- delete orders

Other users can do everything else. Buyer order price (FOB/pc) is visible to everyone on the Line Items tab.

## BOM allocation

Each style has its own BOM sheet; switch between them with the style tabs above the sheet. The sheet works like the Excel material sheet. Every field sits on one line. You type a new material into the last row and edit existing ones directly in the cells. One **Save BOM** saves the whole sheet.

Each material has an **Allocation**, which decides its rows:

- **All colors**: one row for the style's whole quantity (labels, cartons…)
- **By color**: one row per body color (fabric, hangtags…)
- **By size**: one row per size (size labels, drawcords of different lengths…)
- **Color & size**: one row per color/size cell

Order qty per row comes from the assortment. If the assortment changes later, the rows re-sync and keep what was typed. You can type a qty to override it.

Consumption is always **per piece**, so **Total req. = order qty × Cons./pc**. You can type either value and the other is calculated, like an Excel formula. Whichever you typed last wins. In the add row, a typed total is spread over the material's rows at one consumption per piece. There is no wastage and no unit factor, so include any allowance in the numbers you type.

Costing is also one sheet per style, with a price per row, other costs per piece (CM, washing…) and that style's margin. A table underneath compares all styles.

## Run it

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_demo     # optional demo data + users
python manage.py runserver
```

Open http://127.0.0.1:8000/.

`seed_demo` loads the four N&I orders from `order demo.xlsx`. The first one, **WC6916 TRAVIS ZIP CARGO PANT**, is carried through every step using the demo cost sheet's 24 materials, with consumption converted to per piece. The demo sheet prices every row at 2, so the seed uses sample prices instead. It also creates two users:

| User | Password | Role |
|---|---|---|
| `admin` | `admin123` | Admin: sees costing and prices |
| `merchant` | `merchant123` | Merchandiser: no prices |

Change these passwords, or create your own users with `python manage.py createsuperuser`, before real use.
`python manage.py seed_demo --reset` wipes all orders and reloads the demo.

Tests: `python manage.py test apps.orders`

## Layout

```
config/                 settings, urls
apps/orders/
  models.py             Order, OrderLine, AssortmentRow, BOMItem/BOMRow, CostExtra, SupplierPO/Line
  services.py           BOM loading, costing summary, supplier PO generation
  views.py              order workspace (one view per tab action)
  management/commands/seed_demo.py
templates/orders/       home, order workspace (tabs/*.html), PO list, printable PO
static/                 css/style.css (noorbit navy/teal theme), js/app.js (live totals)
```

For production, set `ORBIT_SECRET_KEY`, `ORBIT_DEBUG=0` and `ORBIT_ALLOWED_HOSTS`. Then run `python manage.py collectstatic`.
