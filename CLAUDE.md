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

### Phase 1 fixes (all done on `phase-2-back-to-back`, not yet tested on the VM)

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

Done on this branch (all steps of the plan; not yet tested on the VM):
- `planning/b2b_calculations.py` + `test_b2b_calculations.py`
- Settings section: `default_landed_cost_percent`, `fx_buffer_percent`,
  `delivery_buffer_days`, `default_margin_percent` (also in `planning/settings.py`)
- Custom fields in `install.py`: Quotation / Sales Order `required_by_date`, `priority`;
  Quotation `sourcing_status`, `sourcing_request`; Sales Order `is_back_to_back`;
  Quotation Item / Sales Order Item `needs_sourcing` + sourcing section
  (`supplier_quotation`, `supplier_quotation_item`, `sourcing_supplier`,
  `estimated_landed_cost`, `promised_date`, `purchase_qty`, `excess_qty`,
  `excess_pricing`, `quote_valid_till`); Material Request Item `sales_quotation`,
  `quotation_item`; Supplier Quotation Item `min_order_qty`; Supplier `landed_cost_percent`.
- `planning/back_to_back.py`: `request_sourcing`, `get_supplier_offers`, `select_offers`,
  Quotation `validate` / `before_submit` hooks, `make_back_to_back_purchase_orders`
  (PO lines link the MR line only while it has unordered quantity left, so the MR
  is not over-ordered).
- `public/js/quotation.js`, `public/js/sales_order.js` via `doctype_js`.
- Reports Back-to-Back Order Cost (tree) and Back-to-Back Tracker; SQL in
  `data_sources.get_back_to_back_sales_order_lines` / `get_back_to_back_purchase_lines`.
- Planning no longer counts Back-to-Back Material Requests as pending supply.

Tested on the VM on 2026-10-29: the whole flow works end to end (Quotation → Request
Sourcing → MR → RFQ → two Supplier Quotations → Supplier Offers dialog ranked them with
Best / Requested → Apply Selection set rate 275 from cost 220 and 20% margin → fields
copied to the Sales Order → Create Back-to-Back POs made a draft PO linked to the MR, SO
and Supplier Quotation → both reports show the order). The first migrate failed only
because the VM disk was full (MariaDB 1114 "table is full"); fixed by extending the LV.

### Phase 2 fixes from the VM test (all six done, not yet re-tested on the VM)

1. Offer without a lead time: Promised Date stays empty and the PO "Required By" falls
   back to the Sales Order delivery date. In the Supplier Offers dialog flag offers with
   no lead time ("No lead time" badge, empty Promise shown as a warning) and ask for
   confirmation before applying one; in Quotation `before_submit` warn (msgprint, not
   throw) for sourcing lines without `promised_date`.
2. Quotation form: the "Some items need sourcing…" headline was shown twice once
   (`public/js/quotation.js` line ~29, `frm.dashboard.set_headline` called on more than
   one event). Make it idempotent (clear first, or set it from a single place).
3. Gross Profit on Quotation / Sales Order lines that are sourced is wrong: ERPNext uses
   `valuation_rate`, which is 0 for an item with no stock, so a 275 × 10 line shows 2,750
   profit instead of 550. For sourcing lines, set `valuation_rate` from
   `estimated_landed_cost` (× conversion factor, in company currency) and recompute
   `gross_profit` in the validate hook. Check in the v14 source where selling
   controllers compute `gross_profit` so the value is not overwritten afterwards.
4. Back-to-back PO: the client's PO has a mandatory custom header field
   `expected_delivery_date` (also `production_end_date`, `custom_pi_date` are mandatory
   there). When `Purchase Order` has `expected_delivery_date`, set it from the offer
   (today + lead time) or the schedule date; also set the line `expected_delivery_date`.
   Do not fill the other client fields.
5. Back-to-Back Tracker: put Stage, Days Late, Expected Arrival and Purchase Order right
   after Sales Order; move Item Name / Customer Name further right. The important columns
   are cut off at normal screen width today.
6. Back-to-Back Order Cost: the Sales Order row showed Ordered Qty 10 while its only PO
   child row is a Draft with Ordered Qty 0. Make the parent consistent with the children:
   count submitted PO quantity only, and show draft PO quantity in its own column.

Open questions for the client (no code yet): should back-to-back Material Requests go
through the normal MR approval workflow (it delays asking suppliers), and may sales users
see supplier names and costs in the Supplier Offers dialog (today they can).

Notes on the fixes:
- Fix 3: `valuation_rate` is per stock UOM (gross_profit = (stock_uom_rate -
  valuation_rate) x stock_qty), so it is set to `estimated_landed_cost` without the
  conversion factor. Sales Order also got a `validate` hook. Documents saved before the
  fix keep the old gross profit until saved again (submitted ones stay as they are).
- Fix 4: the header date is the latest line date.
- Phase 1 fix 2: the deduction applies to submitted, not-ordered Purchase MRs except
  Back-to-Back ones; draft MRs are not deducted. Only MRs dated within settings
  `pending_mr_max_age_days` (default 90, 0 = no limit) of the analysis date count: on the
  test site 64 of 77 open Purchase MRs are from 2023-2024 and never closed.
- Phase 1 fix 4: field `calculation_queued_on` on Reorder Parameter Run; Calculate Now
  limited to 3,000 items (`parameter_run.INLINE_ITEM_LIMIT`).

Blanket Orders (2026-10-30, not yet tested on the VM): the purchasing manager creates and
submits Purchasing Blanket Orders by hand (the run's Create Annual Plan button is removed;
`annual_plan.create_annual_plan` stays unused). A submitted agreement valid on the analysis
date with quantity left is the FIRST supplier source (`lead_time.SUPPLIER_BLANKET_ORDER`,
`data_sources.get_item_blanket_orders`; if several, the one ending first). The planning screen
shows the agreement and what is left, values the suggestion at the agreed rate, and warns
`BLANKET_ORDER_EXCEEDED`. Material Request Item custom field `blanket_order` records it. Purchase
Order `validate` hook `planning.blanket_orders.link_purchase_order` ticks Against Blanket Order on
new lines for the PO supplier (respects Buying Settings allowance, clears an MR agreement of
another supplier), so ERPNext's `ordered_qty` on the agreement goes down on submit.
Parameter lines can no longer be added by hand (`in_create`).

Next: user re-tests on the VM (`bench migrate` for the new run field and JSON changes,
`bench build --app procurement_planning`, `bench restart`).

## Phase 3 – later

PO sent / supplier confirmed tracking and alerts (`pi_no` / `custom_pi_date` on the
client's PO look like supplier confirmation), post-receipt price and margin evaluation
(moving average), substitutes with surplus allocation, promotion of back-to-back items to
stock items. Shipment app `purchase_shipment_management` is separate; its fixes need the
production version of that app.
