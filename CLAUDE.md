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
  - frappe: `data_sources.py` (planning and report SQL), `api.py` (planning page API),
    `settings.py`, `lead_time_service.py`, `parameter_run.py`, `annual_plan.py`,
    `back_to_back.py`, `blanket_orders.py`
- `procurement_planning/procurement_planning/doctype/` – Procurement Planning Settings,
  Lead Time Profile (+ Entry), Reorder Parameter Run, Reorder Parameter Line,
  Sourcing Request (+ Item)
- `procurement_planning/procurement_planning/page/procurement_planning/` – planning screen
- `procurement_planning/procurement_planning/report/` – Item Reorder Analysis, Annual Purchase Plan,
  Back-to-Back Order Cost, Back-to-Back Sales Tracker, Back-to-Back Purchase Tracker
- `procurement_planning/planning/back_to_back.py` – back-to-back flow (frappe);
  `public/js/quotation.js`, `sales_order.js`, `material_request.js` via `doctype_js`
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

## Phase 2 – back-to-back (branch `phase-2-back-to-back`, redesigned 2026-10-31)

Purchasing for a specific customer order, for items not in stock or not stocked at all.
Principle (approved by the user): documents that cross between departments carry only
what the other side may see. Purchasing never sees the customer or the selling price;
sales never sees the supplier or the cost. Hidden data that must stay on a sales document
(cost, valuation rate, gross profit) is on permlevel 1. The user sets up roles and
permissions himself; the app ships documents, fields, buttons and logic.

Flow:
1. Quotation (sales): lines ticked `needs_sourcing`; header `required_by_date`, `priority`,
   `sourcing_status` (Pending Sourcing / Ready).
2. Quotation button Back-to-Back > Request Sourcing (`back_to_back.request_sourcing`): a new
   submittable **Sourcing Request** (purchasing) with only those lines, no customer, no
   selling rate. Created with ignore_permissions after checking Quotation write. Lines on an
   active (not cancelled) Sourcing Request are skipped. Only made from Quotations (`in_create`;
   items table cannot add or delete rows; validate refuses a line without `quotation_item`).
3. Sourcing Request > Create > Request for Quotation (`make_request_for_quotation`, mapper);
   RFQ Item and Supplier Quotation Item carry `sourcing_request` / `sourcing_request_item`
   (the standard RFQ -> SQ mapping copies them; the supplier portal path does not).
4. Sourcing Request button Supplier Offers (`get_supplier_offers` / `select_offers`): offers
   made for the line (matched on the quotation line, so offers made for a cancelled request
   it amends count) plus other valid offers, ranked by priority; no-lead-time warning and
   confirmation; excess pricing per line. The request re-prices each chosen offer on save
   (`evaluate_sourcing_line`): landed cost, purchase/excess qty, `pricing_cost` (landed cost,
   or the excess spread over the customer qty when the customer bears it), suggested rate
   (header `margin_percent`, default settings `default_margin_percent`, not below the minimum
   margin) and minimum rate (settings `minimum_margin_percent`), promised date. Status Draft /
   Waiting for Offers / Ready / Submitted / Cancelled.
5. Submit (every line needs an offer; expired offers and missing lead times warn) writes to
   the DRAFT Quotation lines only: `suggested_rate`, `minimum_rate` (per Quotation UOM and
   currency), `promised_date`, `quote_valid_till`, `sourced_stock_qty`, `sourced_qty_locked`
   (customer bears a real excess), `estimated_landed_cost` = pricing cost (permlevel 1),
   valuation rate and gross profit, links to the request line; `sourcing_status` Ready (db
   writes, Quotation modified moves on); Notification Log to the Quotation owner. Cancel clears
   them from a draft Quotation and is refused while a submitted Quotation uses them.
6. Quotation submit (`before_submit_quotation`): blocks lines without a price, a qty above
   the sourced qty or any change when `sourced_qty_locked`, a rate below the minimum (cost and
   current minimum margin in the line's UOM/currency) unless the user has settings
   `below_minimum_rate_role`; warns on a lower qty, an expired or shorter price validity, no
   promised date. Duplicated quotations drop the copied sourcing (`clear_foreign_sourcing`).
7. Sales Order by the standard mapping; `make_sales_order` is overridden to drop
   permlevel 1 fields before the unsaved order goes to the browser and to set each sourced
   line's `delivery_date` to its `promised_date` (unless before the order date; the header
   takes the latest, as ERPNext's validate_delivery_date does); the SO validate hook takes the
   cost from the Quotation Item on the server (`copy_cost_from_quotation`).
8. Sales Order button Back-to-Back > Request Purchase (`request_purchase`): draft Material
   Request (Purchase, `procurement_type` Back-to-Back) with the sourced lines: stock qty,
   warehouse, schedule date = promise - delivery buffer, standard `sales_order` /
   `sales_order_item`, `sourcing_request(_item)`; no customer or rate; ignore_permissions after
   checking SO write; left in draft for the MR approval workflow.
9. Submitted Back-to-Back MR > Create > Back-to-Back Purchase Orders
   (`make_back_to_back_purchase_orders`): one draft PO per supplier and currency at the offer
   chosen on the submitted Sourcing Request; customer line linked to MR and SO lines, MOQ
   excess on a separate unlinked line; `expected_delivery_date` on lines and, when the field
   exists, the header; expired offer warns; a qty not whole in the offer UOM goes in stock UOM
   without the SQ item link. Only one PO row per Supplier Quotation Item carries the link
   (ERPNext's validate_with_previous_doc refuses duplicates): the excess row and a second
   line on the same offer keep `supplier_quotation` and the rate only; maintain_same_rate
   skips rows without the item link. The Blanket Order hook still applies.
10. Receipt and Delivery Note are standard.

Pricing: landed cost = supplier unit cost in company currency x (1 + supplier
`landed_cost_percent` or settings default + FX buffer if foreign currency); suggested =
cost / (1 - margin); minimum = cost / (1 - minimum margin) (`b2b_calculations.sourcing_rates`).

Permlevel 1: custom `estimated_landed_cost`; standard `valuation_rate` and `gross_profit` of
Quotation Item and Sales Order Item (Property Setters in `install.COST_FIELDS`). Permlevel
access is decided by the parent's (Quotation / Sales Order) permission rules.
Known Frappe v14 limit: the response to saving a document (`savedocs` -> `send_updated_docs`)
returns all fields, so a sales user's browser receives permlevel 1 values of the Quotation it
just saved (hidden in the form, visible in developer tools). Stripping them in `on_update`
would corrupt Version records; not done. The form load (`getdoc`) strips them.

Reports: Back-to-Back Order Cost (System Manager by default: cost and margin), Back-to-Back
Sales Tracker (Sales roles: no supplier/PO/cost), Back-to-Back Purchase Tracker (Purchase
roles: per MR line, no customer/selling price). Stage logic: `b2b_calculations.purchase_progress`.

Migrate cleanup (`install.py`): the first design's custom fields (`OBSOLETE_FIELDS`, supplier
and offer on sales lines, `sales_quotation` / `quotation_item` on MR Item, Quotation header
`sourcing_request` to MR) are deleted with their columns; the old Back-to-Back Tracker report
is deleted.

Planning still excludes back-to-back: SO lines with a PO line against them, those PO lines,
and Back-to-Back Material Requests.

Open question for the client: may back-to-back PO lines be drawn from a supplier's Blanket
Order (today they are, when the item is in one).

Notes (phase 1 fixes and the first VM test, still valid):
- Gross profit: `valuation_rate` is per stock UOM (gross_profit = (stock_uom_rate -
  valuation_rate) x stock_qty), so it is set to `estimated_landed_cost` without the
  conversion factor (`back_to_back.set_sourcing_valuation`, Quotation and Sales Order
  validate hooks, after SellingController.validate).
- PO header `expected_delivery_date` is the latest line date.
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
Review 2026-10-30 (checked against v14 source): the hook sizes a line by max(stock_qty, qty)
because ERPNext draws down by stock_qty but `validate_against_blanket_order` compares qty;
it clears `blanket_order` on lines not Against Blanket Order (ERPNext counts any submitted line
with `blanket_order` set); new-line detection relies on `__islocal`, which Frappe keeps until
the row is written. Open question: back-to-back PO lines (sales_order set) are linked to the
supplier's agreement too; the user decides whether to skip them.

VM test 2026-11-01: steps 1-9 of the README test script passed. Step 10 failed with
"Duplicate row 3 with same Supplier Quotation Item" (excess row carried the item link);
fixed, plus SR rows only from the Quotation and SO delivery dates from the promise.

Next: user re-tests step 10 onwards on the VM (see the test script in the README section
"Back-to-back purchasing"); old back-to-back test data need not be migrated.

## Phase 3 – later

PO sent / supplier confirmed tracking and alerts (`pi_no` / `custom_pi_date` on the
client's PO look like supplier confirmation), post-receipt price and margin evaluation
(moving average), substitutes with surplus allocation, promotion of back-to-back items to
stock items. Shipment app `purchase_shipment_management` is separate; its fixes need the
production version of that app.
