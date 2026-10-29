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
- Supplier: Item Default for the company, then Item Supplier, then the latest
  Purchase Order (flagged as inferred).
- Open POs late beyond the tolerance are not counted as supply. Quantities
  shipped on a submitted Purchase Shipment (purchase_shipment_management) count
  at the shipment arrival date.
- Open Sales Orders count as demand only when due within the planning horizon.
- Back-to-back: Sales Order lines with a Purchase Order raised against them,
  and those Purchase Order lines, are excluded from planning.
- Suggested quantity is raised to the Item Minimum Order Qty and rounded up to
  the Item *Purchase Order Multiple*.

### Tests

The calculation modules are pure Python:

```bash
cd apps/procurement_planning
python3 -m unittest procurement_planning.planning.test_calculations
```

#### License

MIT
