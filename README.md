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
| **4. BOM** | Excel-style sheet per style: type, item, placement, color, size, consumption/pc ⇄ total req. No prices or suppliers. Excel and PDF download | Every style has materials |
| **5. Costing** | Price per BOM row, CM/other costs, cost/pc vs FOB, margin per style | Every BOM row has a price |
| **6. Supplier PO** | Choose a supplier per material, then generate one PO per supplier and material type. Staff approve each PO. Move lines between POs, merge POs, PI/LC/ETD/ETA and delivery details, Excel and PDF PO | — |

After login, users land on the list of **running orders**.

Buyer, factory, supplier and material names are typed in directly. There are no master-data modules. Fields autocomplete from values entered before.

## Users and approvals

Every user can use every part of Orbit: orders, assortment, BOM, costing and prices, supplier POs, and all reports.

Two rules sit on top of that:

- **Supplier POs need staff approval.** A *staff* user is one with *staff status* (set in Django admin → Users). New POs start as **Pending approval**. Staff approve them, or send them back with a note, from the PO or from the **Approvals** page. The Approvals page sits in the top menu, with a count of waiting POs. The raiser corrects a PO that was sent back and sends it for approval again. Until a PO is approved, its status stays *Draft* and its Excel/PDF are marked **DRAFT — NOT APPROVED**. Once approved, the approver's name appears under *Authorized signature*.
- **A PO belongs to whoever raised it.** Only that user, or a staff user, can change its lines, move or merge its lines, or delete it. Once a PO is approved its lines are locked for everyone; a staff user can **Reopen** it, after which it needs approving again. Dates, PI/LC and delivery details stay editable by the raiser after approval. The supplier and type do not.

POs raised before approvals existed count as approved. Those with no recorded raiser can only be changed by staff. An order can be deleted by the user who created it, or by staff.

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

## Supplier POs

Every BOM material has a **Type**: Fabric, Lining, Inter-lining, Pocketing, Trims, Accessories, Labels, Packing or Other. Suppliers are not part of the BOM. They are chosen on the Supplier PO tab:

1. **Choose suppliers.** The top of the tab lists every material not on a PO yet. Type a supplier against each one.
2. **Generate.** One PO is raised per supplier *and* type, so a supplier giving both fabric and trims gets two POs. Materials left without a supplier stay in the list.
3. **Adjust.** Tick lines inside a PO and move them to another PO, to a new PO, or back to "not ordered". Tick two or more POs of the same supplier and merge them into one. A PO holding more than one type shows as **Mixed**. The supplier, type, dates, PI and LC of a PO are edited under **Details**.

Order numbers read **ORD-YY-xxxxx** and PO numbers **SPO-YY-xxxxx**: the year it was entered, then its running number.

A PO's **Details** hold the supplier, type, status, dates, PI no., LC no., PI to, PI to location, factory location, destination, ETD and ETA.

Each PO can be **viewed** on screen (click its PO number), or downloaded as an **Excel** document laid out for printing (landscape, one page wide), or as a **PDF** with the same content. It shows those details, each line's placement, body color, color combination, size and spec from the BOM, and the name of the user who raised it under *Prepared by*. Amounts and the total are live formulas. The Costing tab has the same kind of Excel download for a style's cost sheet. The BOM tab downloads a style's BOM, without prices, as Excel or PDF.

## Reports

The **Reports** menu has eight reports. All share one filter bar (status, buyer, ship-date range), and each downloads as Excel or CSV with the filter applied.

| Report | Shows |
|---|---|
| Order register | Every order: qty, value, ship date, status, progress |
| Buyer summary | Orders, pieces and value per buyer |
| Shipment plan | Orders, pieces and value per ship month, and what is overdue |
| Material requirement | Every BOM material: type, requirement, supplier, PO status |
| Supplier summary | POs per supplier: count, types, open vs received |
| Supplier PO register | Every PO with PI, LC, ETD, ETA, status, approval, raiser and approver |
| Costing & margin | Cost per piece against FOB and margin per style |
| Material cost by type | Spend on fabric, trims, labels and packing per order |

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
| `admin` | `admin123` | Staff: approves supplier POs |
| `merchant` | `merchant123` | Merchandiser |

Change these passwords, or create your own users with `python manage.py createsuperuser`, before real use.
`python manage.py seed_demo --reset` wipes all orders and reloads the demo.

Tests: `python manage.py test apps.orders`

## Layout

```
config/                 settings, urls
apps/orders/
  models.py             Order, OrderLine, AssortmentRow, BOMItem/BOMRow, CostExtra, SupplierPO/Line
  services.py           BOM loading, costing summary, supplier PO generation, move and merge
  reports.py            the reports and their Excel/CSV downloads
  exports.py            supplier PO (Excel, PDF) and cost sheet (Excel) documents
  views.py              order workspace (one view per tab action)
  management/commands/seed_demo.py
templates/orders/       home, order workspace (tabs/*.html), PO list, reports
static/                 css/style.css (noorbit navy/teal theme), js/app.js (live totals)
```

## Settings (.env)

Settings are read from a `.env` file in the project folder, next to `manage.py`. Copy `.env.example` to `.env` and fill it in. `.env` is never committed. Variables set in the server's real environment take precedence over the file.

| Variable | Meaning |
|---|---|
| `ORBIT_SECRET_KEY` | Long random string. Keep it secret and keep it unchanged, since changing it logs everyone out |
| `ORBIT_DEBUG` | `1` on your own computer, `0` on the live site |
| `ORBIT_ALLOWED_HOSTS` | Comma-separated host names, e.g. `orbit.asgroupbd.com` |
| `ORBIT_CSRF_TRUSTED_ORIGINS` | Comma-separated origins allowed to post forms, e.g. `https://orbit.asgroupbd.com` |
| `ORBIT_DB_ENGINE` | `sqlite` (default), `postgresql` or `mysql` |
| `ORBIT_DB_NAME` | SQLite: the database file, relative to the project folder (default `db.sqlite3`). Otherwise: the database name |
| `ORBIT_DB_USER`, `ORBIT_DB_PASSWORD`, `ORBIT_DB_HOST`, `ORBIT_DB_PORT` | Connection details for PostgreSQL / MySQL. Install the driver too: `pip install psycopg` or `pip install mysqlclient` |
| `ORBIT_COMPANY_NAME` | Company name on the Excel supplier PO and cost sheet |
| `ORBIT_COMPANY_ADDRESS` | Address line under it |
| `ORBIT_COMPANY_LOGO` | Logo image, relative to the project folder (default `static/image/orbit_logo.png`) |

On the live server, also run `python manage.py collectstatic`.
