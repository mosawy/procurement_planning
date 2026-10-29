# procurement_planning

Frappe app for ERPNext **v14** (frappe 14.101, erpnext 14.92, Python 3.10 on the bench).
Rolling procurement planning for a Saudi distributor (CCTV / networking, Hikvision is
the main brand). Developer: Mohamed Elsawy (Go Live Solutions). He speaks Egyptian
Arabic; reply to him in Arabic, keep code, comments and commit messages in English.

## No bench in the cloud session

There is no Frappe bench or database here. Code is checked offline:

```bash
python3 -m unittest procurement_planning.planning.test_calculations procurement_planning.planning.test_b2b_calculations
find . -name "*.py" -exec python3 -m py_compile {} \;
for f in $(find . -name "*.js"); do node --check "$f"; done
for f in $(find . -name "*.json"); do python3 -c "import json; json.load(open('$f'))"; done
```

Keep calculation logic in pure modules (no `import frappe`) so it is unit-testable.
Before using any ERPNext field, confirm it exists in v14 by fetching the DocType JSON from
`https://raw.githubusercontent.com/frappe/erpnext/version-14/erpnext/<module>/doctype/<name>/<name>.json`.
Frappe NOT NULL rule: Int/Float/Currency/Check columns never accept NULL; write 0.
Int fields left blank save as 0, so treat 0 as "not set" where a blank means "use default".
The user installs on his VM (`bench migrate`, `bench build --app procurement_planning`,
`bench restart`) and reports errors back. Background jobs (`frappe.enqueue`) did NOT run on
his VM; anything enqueued must also be runnable with
`bench --site golive.site1 execute <dotted.path> --kwargs "{...}"`.

The test site `golive.site1` is a copy of the client's data that ends on 2026-09-08, so
demos use analysis date 2026-09-08.

## Layout

- `procurement_planning/planning/` – logic
  - pure: `proposed_calculations.py`, `sap_calculations.py`, `demand_history.py`,
    `lead_time.py`, `b2b_calculations.py`
  - frappe: `data_sources.py` (all SQL), `api.py` (planning page API), `settings.py`,
    `lead_time_service.py`, `parameter_run.py`, `annual_plan.py`
- `procurement_planning/procurement_planning/doctype/` – Procurement Planning Settings,
  Lead Time Profile (+ Entry), Reorder Parameter Run, Reorder Parameter Line
- `procurement_planning/procurement_planning/page/procurement_planning/` – planning screen
- `procurement_planning/procurement_planning/report/` – Item Reorder Analysis, Annual Purchase Plan
- `procurement_planning/install.py` – custom fields on standard DocTypes, created by
  `after_install` / `after_migrate` (no fixtures). Add new custom fields here.
- Permissions: planning page and new DocTypes are System Manager only
  (`permissions.ALLOWED_ROLES`). Back-to-back endpoints should use normal document
  permissions (`frappe.has_permission`) since sales and purchasing users run them.

## Phase 1 – planned purchasing (done, on `main`)

Settings per company → lead times derived from received POs into Lead Time Profiles →
monthly Reorder Parameter Run (calculate, review lines with override reasons, submit =
active) → planning screen uses the active run, creates draft Purchase Material Requests
(`procurement_type = Planned`, `suggested_qty`, `variance_reason`, `suggested_supplier`)
→ annual plan as draft Purchasing Blanket Orders + Annual Purchase Plan report.
Tested end to end by the user on his VM.

### Phase 1 fixes still to do (user asked to do them after phase 2)

1. Supplier inference (`data_sources.get_item_supplier_sources`): rank by quantity bought
   in the window, not latest date, and ignore PO lines with `sales_order` set
   (back-to-back buys). Example found: a Hikvision camera inferred to a local supplier.
2. Subtract submitted, not-yet-ordered Purchase Material Requests from the suggestion
   (today they are shown only), so an item is not requested twice.
3. Done already: approved lines keep their original `supplier_source` (Last PO flag stays).
4. Background calculation of Reorder Parameter Run: detect that it never started (status
   stuck on Calculating) and tell the user, or offer a "Calculate now" path that runs
   inline for small companies.

## Phase 2 – back-to-back (in progress, branch `phase-2-back-to-back`)

Purchasing for a specific customer order, for items not in stock or not stocked at all,
possibly brands the company does not normally sell. Flow agreed with the client:

Quotation (draft, items marked `needs_sourcing`) → purchasing asks suppliers → supplier
offers (standard Supplier Quotation) → purchasing picks an offer per line → sales prices
the quotation (cost + margin) and promises a date → customer accepts → Sales Order →
back-to-back Purchase Order(s) raised against the Sales Order lines.

Decisions already taken:
- Build on standard ERPNext documents only (Quotation, Material Request, Request for
  Quotation, Supplier Quotation, Sales Order, Purchase Order). Do NOT depend on the
  client's custom "Sales Request For Quotation" DocType; that site is a test copy.
- Estimated landed cost = supplier unit cost in company currency × (1 + landed % + FX
  buffer % if foreign currency). Landed % comes from the Supplier custom field
  `landed_cost_percent`, else settings `default_landed_cost_percent`. (Deriving it from
  past Landed Cost Vouchers is a later improvement: only ~23% of receipts have one.)
- Promised date = today + offer lead time + settings `delivery_buffer_days`.
- Supplier minimum order: buy max(need, MOQ). The excess is priced either into the
  customer's unit cost (`Customer Bears Excess`) or put into stock (`Excess to Stock`).
  The PO gets two lines: the customer's quantity linked to the Sales Order line, and the
  excess as a separate unlinked line so planning sees it as normal stock.
- Planning already excludes back-to-back: SO lines that have a PO line with
  `sales_order_item` pointing at them, and those PO lines (`exclude_back_to_back` setting).
- Priority (Urgent / Normal / Flexible) and required-by date on Quotation and Sales
  Order. Urgent ranks offers by earliest promise, others by cost.

Done on this branch:
- `planning/b2b_calculations.py` + `test_b2b_calculations.py`
- Settings section: `default_landed_cost_percent`, `fx_buffer_percent`,
  `delivery_buffer_days`, `default_margin_percent` (also in `planning/settings.py`)

To do, in order:
1. Custom fields in `install.py` (anchors verified in v14):
   - Quotation (after `valid_till`): `required_by_date` Date, `priority` Select
     "\nUrgent\nNormal\nFlexible", `sourcing_status` Select "\nPending Sourcing\nReady for
     Pricing" (read only), `sourcing_request` Link Material Request (read only).
   - Quotation Item: `needs_sourcing` Check (after `item_name`); collapsible section after
     `gross_profit` with `supplier_quotation` Link, `supplier_quotation_item` Data (hidden),
     `sourcing_supplier` Link Supplier, `estimated_landed_cost` Currency (per stock UOM,
     company currency), `promised_date` Date, `purchase_qty` Float, `excess_qty` Float,
     `excess_pricing` Select "\nCustomer Bears Excess\nExcess to Stock",
     `quote_valid_till` Date.
   - Sales Order: `required_by_date`, `priority` (same names so the standard Quotation →
     Sales Order mapping copies them), `is_back_to_back` Check (read only).
   - Sales Order Item: the same sourcing fields with the same names (copied by mapping).
   - Material Request Item: `sales_quotation` Link Quotation, `quotation_item` Data.
   - Supplier Quotation Item: `min_order_qty` Float (after `qty`).
   - Supplier: `landed_cost_percent` Percent (after `default_currency`).
2. `planning/back_to_back.py` (whitelisted, permission-checked):
   - `request_sourcing(quotation, items)`: draft Quotation → draft Purchase Material
     Request, `procurement_type = Back-to-Back`, items carry `sales_quotation` /
     `quotation_item`, warehouse from the quotation line or settings default, schedule date
     from `required_by_date`. Sets `sourcing_status = Pending Sourcing`. Standard ERPNext
     then makes the RFQ (MR → RFQ maps `material_request_item`; RFQ → Supplier Quotation
     copies it too).
   - `get_supplier_offers(quotation)`: per sourcing line, Supplier Quotation Items linked
     through `material_request_item`, plus other valid submitted offers for the same item;
     compute unit cost in company currency per stock UOM (`base_rate / conversion_factor`),
     landed cost, lead time, promised date, MOQ effect, expiry; rank with `rank_offers`.
   - `select_offers(quotation, selections)`: write the chosen offer into the line, set the
     rate from cost and margin when asked, set `sourcing_status = Ready for Pricing` when
     every sourcing line has an offer.
   - Quotation `before_submit` hook: block submit while a sourcing line has no offer; warn
     when the quotation is valid longer than the supplier offer.
   - `make_back_to_back_purchase_orders(sales_order)`: one draft PO per supplier and
     currency, rate from the offer, `sales_order` / `sales_order_item` /
     `supplier_quotation` / `supplier_quotation_item` set, excess on a separate line; skip
     lines that already have a PO; mark `is_back_to_back`.
3. Form scripts via `doctype_js` in `hooks.py`: Quotation buttons "Request Sourcing" and
   "Supplier Offers" (dialog with ranked offers, margin %, excess pricing); Sales Order
   button "Create Back-to-Back POs" and links to the two reports.
4. Script reports:
   - Back-to-Back Order Cost: per Sales Order line, its PO lines with supplier, qty, unit
     cost (actual = Purchase Receipt Item `valuation_rate`, which includes Landed Cost
     Voucher amounts; else estimated), weighted average vs `estimated_landed_cost`,
     selling rate and margin. Tree report (indent).
   - Back-to-Back Tracker: per line, customer, priority, required and promised dates,
     stage (`back_to_back_stage`), expected arrival (Purchase Shipment
     `shipment_arriving_date` when `data_sources.has_shipment_tracking()`, else PO
     schedule date) and days late against the promise.
5. Tests for any new pure logic, offline checks above, README section, commit, push.

## Phase 3 – later

PO sent / supplier confirmed tracking and alerts (`pi_no` / `custom_pi_date` on the
client's PO look like supplier confirmation), post-receipt price and margin evaluation
(moving average), substitutes with surplus allocation, promotion of back-to-back items to
stock items. Shipment app `purchase_shipment_management` is separate; its fixes need the
production version of that app.
