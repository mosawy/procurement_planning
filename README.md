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
all. Built on standard ERPNext documents only.

1. **Quotation** (draft) – set *Required By Date* and *Priority* (Urgent ranks
   offers by earliest promise, others by cost), tick *Needs Sourcing* on the
   lines to buy for this order, save, then *Back-to-Back > Request Sourcing*.
   This makes a draft Purchase Material Request (*Procurement Type*
   Back-to-Back) whose lines point back to the quotation lines. Lines without a
   warehouse use the settings *Default Purchase Warehouse*.
2. **Purchasing** submits the Material Request, makes the *Request for
   Quotation* from it and records the answers as *Supplier Quotations* (set
   *Lead Time in days* or *Expected Delivery Date*, *Valid Till*, and *Supplier
   Min Order Qty* when the supplier sells a minimum). Supplier Quotations made
   from the RFQ stay linked to the quotation line.
3. **Supplier Offers** on the Quotation lists, per line, the linked offers plus
   other valid offers for the item, ranked by priority, with:
   - unit cost in company currency per stock UOM;
   - estimated landed cost = unit cost × (1 + landed % + FX buffer % when the
     offer is in a foreign currency). Landed % is the Supplier's *Landed Cost %*,
     else the settings default;
   - the supplier minimum: buy max(need, MOQ); the excess is either priced into
     the customer's unit cost (*Customer Bears Excess*) or put into stock
     (*Excess to Stock*);
   - promised date = today + offer lead time + settings *Delivery Buffer Days*;
   - expired offers last.
   *Apply Selection* writes the chosen offer into the line and, with *Set rate
   from cost and margin*, sets the rate for the margin % (gross margin on the
   selling price). When every sourcing line has an offer the quotation is
   *Ready for Pricing*.
4. **Submit** is blocked while a sourcing line has no offer, and warns when the
   quotation is valid longer than a supplier offer.
5. **Sales Order** – made from the Quotation as usual; priority, dates and the
   sourcing fields are copied. *Back-to-Back > Create Back-to-Back POs* makes
   one draft Purchase Order per supplier and currency at the offer rate. The
   customer's quantity is linked to the Sales Order line; a supplier minimum
   above it goes on a separate unlinked line into stock, so planning treats it
   as normal stock. Lines already on a Purchase Order are skipped.
6. **Reports** – *Back-to-Back Order Cost* (per Sales Order line its Purchase
   Order lines, received quantity at Purchase Receipt valuation which includes
   Landed Cost Vouchers, the rest at the estimate; margin) and *Back-to-Back
   Tracker* (stage, expected arrival from Purchase Shipments when installed,
   days late against the promise).

Planning leaves back-to-back out: Sales Order lines with a Purchase Order line
against them, those Purchase Order lines, and Back-to-Back Material Requests.

The endpoints use normal document permissions, so sales and purchasing users
can run them; the two reports are open to Sales and Purchase roles and show
only Sales Orders the user can read.

### Tests

The calculation modules are pure Python:

```bash
cd apps/procurement_planning
python3 -m unittest procurement_planning.planning.test_calculations procurement_planning.planning.test_b2b_calculations
```

#### License

MIT
