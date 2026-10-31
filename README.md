## Procurement Planning

Rolling procurement planning for ERPNext v14: per-company settings, lead times
derived from purchase history, a monthly approval of reorder parameters, a
planning screen that turns suggestions into Material Requests, and an annual
plan on Purchasing Blanket Orders.

### Install or update

```bash
cd ~/golive-bench
bench --site <site> install-app procurement_planning   # first time only
bench --site <site> migrate                             # creates DocTypes and custom fields
bench build --app procurement_planning
bench restart
```

`migrate` also (re)creates the custom fields listed in `procurement_planning/install.py`.

### Monthly flow

1. **Settings** – create a *Procurement Planning Settings* record per company
   (analysis months, safety stock days, review period, stock-out threshold,
   late PO tolerance, back-to-back exclusion, default purchase warehouse).
2. **Lead times** – on the settings form click *Derive Lead Times*. Lead times
   per supplier and per supplier + brand are calculated from received Purchase
   Orders (median days from PO date to first receipt) and stored as dated
   entries in *Lead Time Profile*. Manual entries are never overwritten.
3. **Parameter run** – create a *Reorder Parameter Run* (company + analysis
   date), click *Calculate Parameters*, review lines (*Review Lines* opens an
   editable report view), give a reason for any changed value, then submit.
   The submitted run becomes the active one for the company.
   *Calculate Parameters* runs as a background job. When background workers do
   not run, the form says so after a few minutes; use *Calculate Now* (inside
   the request, up to 3,000 items) or run on the server:
   `bench --site <site> execute procurement_planning.planning.parameter_run.calculate --kwargs "{'run_name': '<run>'}"`.
4. **Planning screen** (`/app/procurement-planning`) – uses the active run's
   approved parameters, shows supplier, lead time source and suggested value,
   and creates a draft Purchase Material Request from selected rows. A
   quantity different from the suggestion needs a variance reason.
5. **Annual plan** – from a submitted run, *Create Annual Plan* makes one draft
   Purchasing Blanket Order per supplier. The *Annual Purchase Plan* report
   shows planned, ordered, received and remaining quantities.

### Calculation rules

- Average monthly sales leave out months in which the item was out of stock on
  at least the configured share of days.
- Lead time: Item, then Lead Time Profile (supplier + brand, supplier, brand),
  then the company default. Items with none are flagged.
- Supplier: Item Default for the company, then Item Supplier, then the supplier
  the item was bought from most in the supplier history window (flagged as
  inferred; back-to-back Purchase Order lines are ignored).
- Open POs late beyond the tolerance are not counted as supply. Quantities
  shipped on a submitted Purchase Shipment (purchase_shipment_management) count
  at the shipment arrival date.
- Open Sales Orders count as demand only when due within the planning horizon.
- Back-to-back: Sales Order lines with a Purchase Order raised against them,
  and those Purchase Order lines, are excluded from planning.
- Submitted Purchase Material Requests not yet ordered (Back-to-Back ones
  aside) are subtracted from the suggestion, so an item is not requested twice.
  They are not counted as supply for the stock-out risk.
- Suggested quantity is raised to the Item Minimum Order Qty and rounded up to
  the Item *Purchase Order Multiple*.

### Back-to-back purchasing

Buying for a specific customer order, for items not in stock or not stocked at
all, on standard ERPNext documents plus one purchasing document, the
*Sourcing Request*. Sales and purchasing never see each other's data:
purchasing documents carry no customer or selling price, sales documents no
supplier or cost. The cost the price is built on, the valuation rate and the
gross profit of sales lines are on permlevel 1.

1. **Quotation** (sales) – set *Required By Date* and *Priority*, tick *Needs
   Sourcing* on the lines to buy for this order, save, then *Back-to-Back >
   Request Sourcing*. Purchasing gets a *Sourcing Request* with those lines
   only. The quotation shows *Pending Sourcing*.
2. **Sourcing Request** (purchasing) – *Create > Request for Quotation*, send
   it to suppliers, record their answers as *Supplier Quotations* made from the
   RFQ (set *Lead Time in days* or *Expected Delivery Date*, *Valid Till*, and
   *Supplier Min Order Qty* when the supplier sells a minimum).
3. **Supplier Offers** on the Sourcing Request – per line the offers made for
   it and other valid offers for the item, ranked by priority (Urgent: earliest
   promise; others: cost), with landed cost, supplier minimum and excess, the
   resulting suggested and minimum rate, and the promise. Choose one per line
   and how a supplier minimum above the need is priced (*Excess to Stock* or
   *Customer Bears Excess*). The header *Margin %* sets the suggested rate.
4. **Submit** the Sourcing Request – every line needs an offer. The draft
   quotation lines get the suggested and minimum rate (in the quotation's UOM
   and currency), the promised date and how long the price holds; the
   quotation turns *Ready* and its owner is notified.
5. **Price and submit the Quotation** – a rate below the minimum rate blocks
   submit unless the user has the settings *Role Allowed Below Minimum Rate*.
   A quantity above the sourced one blocks (any change when the customer bears
   the supplier minimum); a lower quantity, an expired price or a missing
   promise only warn.
6. **Sales Order** – made from the quotation as usual (sourced lines take
   their promised date as delivery date); then *Back-to-Back >
   Request Purchase* makes a draft *Material Request* (Back-to-Back) with the
   sourced lines and no customer or price. It goes through the normal approval.
7. **Purchase Orders** – on the submitted Material Request, *Create >
   Back-to-Back Purchase Orders* makes one draft PO per supplier and currency
   at the chosen offers. The customer's quantity is linked to the Material
   Request and Sales Order lines; a supplier minimum above it goes on a
   separate line into stock, so planning treats it as normal stock.
8. **Receipt and delivery** are standard.

Pricing: landed cost = supplier unit cost in company currency × (1 + the
Supplier's *Landed Cost %* or the settings default + *Exchange Rate Buffer %*
for a foreign currency). Suggested rate = cost ÷ (1 − margin); minimum rate =
cost ÷ (1 − *Minimum Margin %*). With *Customer Bears Excess* the cost is the
whole purchase spread over the customer's quantity.

Reports: *Back-to-Back Order Cost* (management: actual and estimated cost,
margin), *Back-to-Back Sales Tracker* (sales: stage, promise, expected
arrival, days late) and *Back-to-Back Purchase Tracker* (purchasing: Sourcing
Request, supplier, Purchase Orders, stage, days late).

Set up after installing: give the management role permlevel 1 (read) on
*Quotation* and *Sales Order* (Role Permissions Manager), and restrict the
standard *Gross Profit* report, which shows buying cost. Sourcing Request
ships with Purchase Manager / Purchase User permissions.

Planning leaves back-to-back out: Sales Order lines with a Purchase Order line
against them, those Purchase Order lines, and Back-to-Back Material Requests.

#### Test script

On `golive.site1`, as Administrator unless noted (or with one sales user, one
purchasing user and one manager to see the separation):

1. *Procurement Planning Settings* for the company: Default Margin % 20,
   Minimum Margin % 10, Default Purchase Warehouse set. Leave Role Allowed
   Below Minimum Rate empty.
2. New Quotation for a customer, two items (A: 10 Nos, B: 4 Nos), Priority
   Normal, Required By Date in a month. Tick *Needs Sourcing* on both, save,
   *Back-to-Back > Request Sourcing*. Expect a message naming the Sourcing
   Request and the status *Pending Sourcing*. Submit must be refused
   ("waiting for a price from purchasing").
3. Open the Sourcing Request: two lines, no customer, no rate, status Draft.
   *Create > Request for Quotation*, add two suppliers and a message, save and
   submit. The Sourcing Request status becomes *Waiting for Offers* on its next
   save.
4. Use suppliers that quote in the company currency and have no Landed Cost %
   of their own (so the settings default 10 % applies) to match the numbers
   below. From the RFQ make a Supplier Quotation for supplier 1: A at 200 (lead time
   30), B at 50 with Supplier Min Order Qty 10 (lead time 20); submit. Supplier
   2: A at 190 with no lead time and no expected delivery date; submit.
5. Sourcing Request > *Supplier Offers*: A shows both offers, *Requested*
   badges, supplier 2 flagged *No lead time / No promise*. Choose supplier 2
   for A: a confirmation appears; cancel it and choose supplier 1 instead. For
   B choose supplier 1 and set *Customer Bears Excess*. Apply. Expect on the
   lines: A landed cost 220 (10 % landed), pricing cost 220, suggested 275,
   minimum 244.44; B purchase 10 / excess 6, pricing cost 55 × 10 / 4 = 137.50.
6. Submit the Sourcing Request. The quotation owner gets a notification. On
   the quotation (reload) the lines show Suggested Rate, Minimum Rate, Promised
   Date, Price Valid Till, Sourced Qty; status *Ready*. As a sales user without
   permlevel 1, the Estimated Cost, Valuation Rate and Gross Profit fields are
   not shown.
7. Set A's rate to 240 and submit: refused (below minimum 244.44). Set 275.
   Change B's qty to 3: submit refused (customer bears the excess). Put B back
   to 4 and set its rate to its suggested rate; submit.
8. Make the Sales Order from the quotation and submit. As the manager the
   gross profit of A is (275 − 220) × 10 = 550.
9. Sales Order > *Back-to-Back > Request Purchase*: a draft Material Request
   (Back-to-Back), no customer or rate on it, Required By = promise − delivery
   buffer. Running it again reports the lines as already requested.
10. Approve / submit the Material Request, then *Create > Back-to-Back
    Purchase Orders*: one draft PO for supplier 1 with A 10, B 4 linked to the
    Sales Order and B 6 on a separate line without it; expected delivery dates
    set. Submit the PO.
11. Reports: *Back-to-Back Sales Tracker* (stage Ordered, no supplier column),
    *Back-to-Back Purchase Tracker* (supplier, PO, no customer), *Back-to-Back
    Order Cost* as the manager.
12. Cancel test: on a second quotation, request sourcing, submit the Sourcing
    Request, then cancel it: the quotation lines lose their prices and the
    quotation is *Pending Sourcing* again; amend and submit the request to
    return the prices.

### Tests

The calculation modules are pure Python:

```bash
cd apps/procurement_planning
python3 -m unittest procurement_planning.planning.test_calculations procurement_planning.planning.test_b2b_calculations
```

#### License

MIT
