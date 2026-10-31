# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Read-only data sources for procurement planning.

Every getter returns ``{item_code: values}`` for exactly one company, with all
quantities in stock UOM. Only active stock items are considered: enabled,
``is_stock_item = 1`` and not a variant template.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, get_last_day, getdate, today

from procurement_planning.planning.lead_time import pick_blanket_order, pick_history_supplier

# Standard Warehouse Type created by ERPNext (setup install_fixtures).
TRANSIT_WAREHOUSE_TYPE = "Transit"

# Stock Ledger voucher types that represent deliveries to customers. Sales
# Invoices only post stock ledger entries when update_stock = 1, so a delivery
# billed later by an invoice is counted once, on its Delivery Note.
SALES_VOUCHER_TYPES = ("Delivery Note", "Sales Invoice")


def build_query_params(company, item_group=None, analysis_months=None, item_code=None, analysis_date=None):
	if not company:
		frappe.throw(_("Company is required"))

	if not frappe.has_permission("Company", "read", company):
		frappe.throw(_("Not permitted to read Company {0}").format(company), frappe.PermissionError)

	analysis_date = getdate(analysis_date or today())
	from_date, to_date = get_analysis_period(analysis_months, analysis_date)
	params = frappe._dict(
		company=company, from_date=from_date, to_date=to_date, item_group=None, analysis_date=analysis_date
	)

	if item_group:
		lft, rgt = frappe.db.get_value("Item Group", item_group, ["lft", "rgt"]) or (None, None)
		if lft is None:
			frappe.throw(_("Item Group {0} does not exist").format(item_group))
		params.update(item_group=item_group, ig_lft=lft, ig_rgt=rgt)

	if item_code:
		if not frappe.db.exists("Item", item_code):
			frappe.throw(_("Item {0} does not exist").format(item_code))
		params.item_code = item_code

	return params


def get_analysis_period(analysis_months, reference_date=None):
	"""Return (from_date, to_date) covering the last N completed calendar months."""
	if analysis_months in (None, ""):
		analysis_months = 12

	months = cint(analysis_months)
	if months < 1 or flt(analysis_months) != months:
		frappe.throw(_("Analysis Months must be a positive whole number"))

	reference = getdate(reference_date or today())
	to_date = get_last_day(add_months(reference, -1))
	from_date = get_first_day(add_months(reference, -months))
	return from_date, to_date


def get_items(params):
	sap_code = "i.sap_code" if _has_field("Item", "sap_code") else "null"
	order_multiple = (
		"i.purchase_order_multiple" if _has_field("Item", "purchase_order_multiple") else "0"
	)

	rows = frappe.db.sql(
		f"""
		select
			i.name as item_code, i.item_name, {sap_code} as sap_code, i.stock_uom,
			i.lead_time_days, i.min_order_qty, i.safety_stock, i.creation, i.brand,
			i.last_purchase_rate, {order_multiple} as order_multiple
		from `tabItem` i
		where {_item_conditions(params)}
		order by i.name
		""",
		params,
		as_dict=True,
	)
	return {row.item_code: row for row in rows}


def count_items(params):
	return frappe.db.sql(f"select count(*) from `tabItem` i where {_item_conditions(params)}", params)[0][0]


def get_stock_balances(params):
	"""Bin.actual_qty over every leaf warehouse of the company.

	Reservation and transit stock are part of current stock and are only broken
	out for information.
	"""
	if _has_field("Warehouse", "default_reservation"):
		# alqurishi_customizations moves reserved stock into the warehouse set as
		# Warehouse.default_reservation of the selling warehouse.
		is_reservation = """w.name in (
			select rw.default_reservation from `tabWarehouse` rw
			where ifnull(rw.default_reservation, '') != ''
		)"""
	else:
		is_reservation = "0 = 1"

	rows = frappe.db.sql(
		f"""
		select
			b.item_code,
			sum(b.actual_qty) as current_stock,
			sum(case when {is_reservation} then b.actual_qty else 0 end) as reservation_stock,
			sum(case when w.warehouse_type = %(transit_type)s then b.actual_qty else 0 end) as transit_stock
		from `tabBin` b
		inner join `tabWarehouse` w on w.name = b.warehouse
		inner join `tabItem` i on i.name = b.item_code
		where w.company = %(company)s
			and w.is_group = 0
			and {_item_conditions(params)}
		group by b.item_code
		""",
		dict(params, transit_type=TRANSIT_WAREHOUSE_TYPE),
		as_dict=True,
	)
	return {row.item_code: row for row in rows}


def get_net_sales(params):
	"""Stock-movement-based net sales over the analysis period: quantity shipped to
	customers minus returns."""
	net_sales = {}
	for item_code, _posting_date, actual_qty in _get_sales_movements(params, params.from_date, params.to_date):
		net_sales[item_code] = net_sales.get(item_code, 0) - flt(actual_qty)

	return {
		item_code: frappe._dict(item_code=item_code, net_sales_qty=qty) for item_code, qty in net_sales.items()
	}


def get_monthly_net_sales(params, from_date, to_date):
	"""Stock-movement-based net sales per calendar month: {item_code: {"YYYY-MM": qty}}."""
	monthly = {}
	for item_code, posting_date, actual_qty in _get_sales_movements(params, from_date, to_date):
		months = monthly.setdefault(item_code, {})
		month = getdate(posting_date).strftime("%Y-%m")
		months[month] = months.get(month, 0) - flt(actual_qty)

	return monthly


def _get_sales_movements(params, from_date, to_date):
	"""(item_code, posting_date, actual_qty) of customer deliveries and returns.

	Cancelled vouchers are excluded through is_cancelled (both the original and
	the reversing entries are flagged). Stock Entries (transfers, reservations,
	issues) and Delivery Notes / Sales Invoices to internal customers (ERPNext
	internal and inter-company transfers) are never included.
	"""
	if _has_field("Stock Ledger Entry", "posting_datetime"):
		# Indexed column; posting_date lost its index when ERPNext dropped posting_sort_index.
		period = "sle.posting_datetime >= %(from_datetime)s and sle.posting_datetime < %(to_datetime)s"
	else:
		period = "sle.posting_date between %(from_date)s and %(to_date)s"

	item_filter = "and sle.item_code = %(item_code)s" if params.get("item_code") else ""

	# Item conditions and the per-item sum are applied in Python: an Item join or
	# a GROUP BY makes the optimizer walk the item_code index over the whole
	# ledger history instead of the indexed analysis period.
	eligible_items = set(
		frappe.db.sql_list(f"select i.name from `tabItem` i where {_item_conditions(params)}", params)
	)

	rows = frappe.db.sql(
		f"""
		select sle.item_code, sle.posting_date, sle.actual_qty
		from `tabStock Ledger Entry` sle
		where sle.company = %(company)s
			and sle.is_cancelled = 0
			and sle.voucher_type in %(voucher_types)s
			and {period}
			{item_filter}
			and not exists (
				select 1 from `tabDelivery Note` dn
				where sle.voucher_type = 'Delivery Note'
					and dn.name = sle.voucher_no
					and dn.is_internal_customer = 1
			)
			and not exists (
				select 1 from `tabSales Invoice` si
				where sle.voucher_type = 'Sales Invoice'
					and si.name = sle.voucher_no
					and si.is_internal_customer = 1
			)
		""",
		dict(
			params,
			voucher_types=SALES_VOUCHER_TYPES,
			from_date=from_date,
			to_date=to_date,
			from_datetime=f"{from_date} 00:00:00",
			to_datetime=f"{add_days(to_date, 1)} 00:00:00",
		),
	)

	return [row for row in rows if row[0] in eligible_items]


def get_open_sales_orders(params):
	"""Undelivered Sales Order quantity in stock UOM.

	delivered_qty is in the order UOM and already nets returns, matching how
	ERPNext computes Bin.reserved_qty.
	"""
	result = {}
	for item_code, lines in get_open_sales_order_lines(params).items():
		result[item_code] = frappe._dict(
			item_code=item_code, open_so_qty=sum(line[1] for line in lines)
		)
	return result


def get_open_sales_order_lines(params):
	"""Undelivered Sales Order quantity per line:
	{item_code: [(delivery_date or None, qty, is_back_to_back), ...]}.

	A line is back-to-back when a submitted Purchase Order line was raised
	against it, so it is covered by its own purchase and not by stock.
	"""
	rows = frappe.db.sql(
		f"""
		select
			soi.item_code,
			coalesce(soi.delivery_date, so.delivery_date) as delivery_date,
			(soi.qty - soi.delivered_qty) * soi.conversion_factor as open_qty,
			b2b.linked is not null as is_back_to_back
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		inner join `tabItem` i on i.name = soi.item_code
		left join ({_back_to_back_links_query()}) b2b on {_back_to_back_join("b2b", "soi")}
		where so.docstatus = 1
			and so.company = %(company)s
			and so.status not in ('Closed', 'On Hold')
			and soi.qty > soi.delivered_qty
			and ifnull(soi.delivered_by_supplier, 0) = 0
			and {_item_conditions(params)}
		""",
		params,
		as_dict=True,
	)

	result = {}
	for row in rows:
		result.setdefault(row.item_code, []).append(
			(getdate(row.delivery_date) if row.delivery_date else None, flt(row.open_qty), bool(row.is_back_to_back))
		)
	return result


def get_open_purchase_orders(params):
	"""Unreceived Purchase Order quantity in stock UOM and the nearest expected date."""
	result = {}
	for item_code, lines in get_open_purchase_orders_by_date(params).items():
		dates = [line[0] for line in lines if line[0]]
		result[item_code] = frappe._dict(
			item_code=item_code,
			open_po_qty=sum(line[1] for line in lines),
			next_expected_date=min(dates) if dates else None,
		)

	return result


def get_open_purchase_orders_by_date(params):
	"""Unreceived Purchase Order quantity in stock UOM:
	{item_code: [(expected_date or None, qty, in_transit, is_back_to_back), ...]}.

	The expected date of a line falls back from the PO header
	expected_delivery_date (custom field, when present) to the line
	expected_delivery_date and finally the line schedule_date. Lines without any
	date keep None and are never treated as available today.

	When purchase_shipment_management is installed, the part of a line that is
	shipped but not yet received is returned separately as in transit, dated by
	the latest arrival date of its submitted shipments.

	A line raised against a Sales Order is back-to-back.
	"""
	date_sources = []
	if _has_field("Purchase Order", "expected_delivery_date"):
		date_sources.append("po.expected_delivery_date")
	date_sources += ["poi.expected_delivery_date", "poi.schedule_date"]

	shipments = has_shipment_tracking()
	shipment_columns = (
		"ifnull(poi.shipment_quantity, 0) as shipped_qty, shp.arrival_date"
		if shipments
		else "0 as shipped_qty, null as arrival_date"
	)
	shipment_join = (
		"""left join (
			select psi.name_related as po_item, max(ps.shipment_arriving_date) as arrival_date
			from `tabPurchase Shipment Item` psi
			inner join `tabPurchase Shipment` ps on ps.name = psi.parent
			where ps.docstatus = 1 and ifnull(psi.name_related, '') != ''
			group by psi.name_related
		) shp on shp.po_item = poi.name"""
		if shipments
		else ""
	)

	rows = frappe.db.sql(
		f"""
		select
			poi.item_code,
			coalesce({", ".join(date_sources)}) as expected_date,
			poi.qty, poi.received_qty, poi.conversion_factor,
			ifnull(poi.sales_order, '') != '' as is_back_to_back,
			{shipment_columns}
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		inner join `tabItem` i on i.name = poi.item_code
		{shipment_join}
		where po.docstatus = 1
			and po.company = %(company)s
			and po.status not in ('Closed', 'Delivered')
			and poi.qty > poi.received_qty
			and ifnull(poi.delivered_by_supplier, 0) = 0
			and {_item_conditions(params)}
		""",
		params,
		as_dict=True,
	)

	result = {}
	for row in rows:
		factor = flt(row.conversion_factor) or 1
		open_qty = flt(row.qty) - flt(row.received_qty)
		in_transit_qty = 0
		if row.arrival_date:
			in_transit_qty = min(open_qty, max(0, flt(row.shipped_qty) - flt(row.received_qty)))

		expected_date = getdate(row.expected_date) if row.expected_date else None
		lines = result.setdefault(row.item_code, [])
		if in_transit_qty > 0:
			lines.append((getdate(row.arrival_date), in_transit_qty * factor, True, bool(row.is_back_to_back)))
		if open_qty - in_transit_qty > 0:
			lines.append(
				(expected_date, (open_qty - in_transit_qty) * factor, False, bool(row.is_back_to_back))
			)

	return result


def has_shipment_tracking():
	"""True when purchase_shipment_management tracks shipments against PO items."""
	return (
		frappe.db.exists("DocType", "Purchase Shipment")
		and _has_field("Purchase Shipment Item", "name_related")
		and _has_field("Purchase Shipment", "shipment_arriving_date")
		and _has_field("Purchase Order Item", "shipment_quantity")
	)


def _back_to_back_links_query():
	"""Distinct Sales Order lines (or Sales Order + item) that a submitted PO line was raised against."""
	if _has_field("Purchase Order Item", "sales_order_item"):
		return """
			select distinct poi.sales_order_item as so_detail, 1 as linked
			from `tabPurchase Order Item` poi
			inner join `tabPurchase Order` po on po.name = poi.parent
			where po.docstatus = 1 and ifnull(poi.sales_order_item, '') != ''
		"""
	return """
		select distinct poi.sales_order, poi.item_code, 1 as linked
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and ifnull(poi.sales_order, '') != ''
	"""


def _back_to_back_join(link_alias, soi_alias):
	if _has_field("Purchase Order Item", "sales_order_item"):
		return f"{link_alias}.so_detail = {soi_alias}.name"
	return f"{link_alias}.sales_order = {soi_alias}.parent and {link_alias}.item_code = {soi_alias}.item_code"


def get_pending_purchase_requests(params, max_age_days=0):
	"""Purchase Material Request quantity not yet converted into a Purchase Order.

	Material Request Item.ordered_qty is maintained in stock UOM. max_age_days > 0
	leaves out requests dated more than that many days before the analysis date:
	old requests that were never closed are not live demand on purchasing.
	"""
	age_filter = ""
	values = dict(params)
	if cint(max_age_days) > 0:
		age_filter = "and mr.transaction_date >= %(pending_mr_from)s"
		values["pending_mr_from"] = add_days(params.get("analysis_date") or today(), -cint(max_age_days))

	rows = frappe.db.sql(
		f"""
		select mri.item_code, sum(mri.stock_qty - mri.ordered_qty) as pending_pr_qty
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		inner join `tabItem` i on i.name = mri.item_code
		where mr.docstatus = 1
			and mr.company = %(company)s
			and mr.material_request_type = 'Purchase'
			and ifnull(mr.procurement_type, '') != 'Back-to-Back'
			and mr.status not in ('Stopped', 'Closed')
			and mri.stock_qty > mri.ordered_qty
			{age_filter}
			and {_item_conditions(params)}
		group by mri.item_code
		""",
		values,
		as_dict=True,
	)
	return {row.item_code: row for row in rows}


def get_stock_movements(params, from_date):
	"""Every stock movement of the company from from_date until now:
	{item_code: [(posting_date, actual_qty), ...]}.

	All voucher types count (receipts, transfers, deliveries, adjustments): a
	transfer between two warehouses of the company nets to zero on the same day.
	Used with the current Bin balance to rebuild daily balances for stock-out
	detection without reading the ledger before from_date.
	"""
	if _has_field("Stock Ledger Entry", "posting_datetime"):
		period = "sle.posting_datetime >= %(from_datetime)s"
	else:
		period = "sle.posting_date >= %(from_date)s"

	item_filter = "and sle.item_code = %(item_code)s" if params.get("item_code") else ""
	eligible_items = set(
		frappe.db.sql_list(f"select i.name from `tabItem` i where {_item_conditions(params)}", params)
	)

	rows = frappe.db.sql(
		f"""
		select sle.item_code, sle.posting_date, sle.actual_qty
		from `tabStock Ledger Entry` sle
		where sle.company = %(company)s
			and sle.is_cancelled = 0
			and {period}
			{item_filter}
		""",
		dict(params, from_date=from_date, from_datetime=f"{from_date} 00:00:00"),
	)

	result = {}
	for item_code, posting_date, actual_qty in rows:
		if item_code in eligible_items:
			result.setdefault(item_code, []).append((getdate(posting_date), flt(actual_qty)))
	return result


def get_item_supplier_sources(params, history_months):
	"""Supplier evidence per item, for lead_time.resolve_supplier:
	{item_code: {"item_default": ..., "item_supplier": ..., "last_po": ...}}.

	- item_default: Item Default.default_supplier for the company
	- item_supplier: first Item Supplier row
	- last_po: supplier the item was bought from most (stock UOM quantity) on
	  submitted Purchase Orders of the company in the history window ending on
	  the analysis date; ties go to the latest order, then more orders.
	  Back-to-back lines (sales_order set) are ignored: they follow one
	  customer's order, not the normal source of the item.
	"""
	result = {}

	for item_code, supplier in frappe.db.sql(
		"""
		select d.parent, d.default_supplier
		from `tabItem Default` d
		where d.parenttype = 'Item' and d.company = %(company)s and ifnull(d.default_supplier, '') != ''
		""",
		params,
	):
		result.setdefault(item_code, {})["item_default"] = supplier

	for item_code, supplier in frappe.db.sql(
		"""
		select s.parent, s.supplier
		from `tabItem Supplier` s
		where s.parenttype = 'Item' and ifnull(s.supplier, '') != ''
		order by s.parent, s.idx
		"""
	):
		result.setdefault(item_code, {}).setdefault("item_supplier", supplier)

	history_from = add_months(params.analysis_date, -cint(history_months or 24))
	rows = frappe.db.sql(
		f"""
		select poi.item_code, po.supplier, sum(poi.stock_qty) as qty,
			max(po.transaction_date) as last_date, count(distinct po.name) as orders
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		inner join `tabItem` i on i.name = poi.item_code
		where po.docstatus = 1
			and po.company = %(company)s
			and po.transaction_date between %(history_from)s and %(analysis_date)s
			and ifnull(poi.sales_order, '') = ''
			and {_item_conditions(params)}
		group by poi.item_code, po.supplier
		""",
		dict(params, history_from=history_from),
		as_dict=True,
	)
	candidates = {}
	for row in rows:
		candidates.setdefault(row.item_code, []).append(
			(row.supplier, flt(row.qty), getdate(row.last_date), cint(row.orders))
		)
	for item_code, item_candidates in candidates.items():
		result.setdefault(item_code, {})["last_po"] = pick_history_supplier(item_candidates)

	return result


def get_active_blanket_orders(company, on_date, supplier=None, item_codes=None):
	"""{item_code: [agreement]} of submitted Purchasing Blanket Orders of the
	company valid on on_date. Each agreement: blanket_order, supplier, rate,
	currency, exchange_rate, base_rate, qty, ordered_qty, remaining (stock UOM;
	ordered = submitted POs linked to it, as ERPNext keeps it), to_date.

	A Blanket Order has no currency in v14: its rate is used as the PO rate in
	the PO currency, i.e. the supplier's. The agreement currency is the
	Supplier's default currency (else the company's); base_rate converts the
	rate to the company currency on on_date (None when no exchange rate exists).
	"""
	conditions = [
		"bo.blanket_order_type = 'Purchasing'",
		"bo.docstatus = 1",
		"bo.company = %(company)s",
		"%(on_date)s between bo.from_date and bo.to_date",
	]
	values = dict(company=company, on_date=getdate(on_date))
	if supplier:
		conditions.append("bo.supplier = %(supplier)s")
		values["supplier"] = supplier
	if item_codes is not None:
		if not item_codes:
			return {}
		conditions.append("boi.item_code in %(item_codes)s")
		values["item_codes"] = tuple(item_codes)

	rows = frappe.db.sql(
		f"""
		select boi.item_code, bo.name as blanket_order, bo.supplier, bo.to_date,
			boi.rate, boi.qty, ifnull(boi.ordered_qty, 0) as ordered_qty,
			sup.default_currency as supplier_currency
		from `tabBlanket Order` bo
		inner join `tabBlanket Order Item` boi on boi.parent = bo.name and boi.parenttype = 'Blanket Order'
		left join `tabSupplier` sup on sup.name = bo.supplier
		where {" and ".join(conditions)}
		""",
		values,
		as_dict=True,
	)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	rates = get_exchange_rates(
		{row.supplier_currency or company_currency for row in rows}, company_currency, on_date
	)
	result = {}
	for row in rows:
		currency = row.supplier_currency or company_currency
		exchange_rate = rates.get(currency)
		result.setdefault(row.item_code, []).append(
			dict(
				blanket_order=row.blanket_order,
				supplier=row.supplier,
				to_date=getdate(row.to_date),
				rate=flt(row.rate),
				currency=currency,
				exchange_rate=exchange_rate,
				base_rate=flt(row.rate) * exchange_rate if exchange_rate else None,
				qty=flt(row.qty),
				ordered_qty=flt(row.ordered_qty),
				remaining=flt(row.qty) - flt(row.ordered_qty),
			)
		)
	return result


def get_exchange_rates(currencies, to_currency, on_date):
	"""{currency: rate to to_currency on on_date} from ERPNext's Currency Exchange
	records (or its configured provider); None when no rate is found."""
	from erpnext.setup.utils import get_exchange_rate

	result = {}
	for currency in currencies:
		rate = get_exchange_rate(currency, to_currency, str(getdate(on_date)), "for_buying")
		result[currency] = flt(rate) or None
	return result


def get_item_blanket_orders(company, on_date):
	"""{item_code: agreement} the item is bought under on on_date (see lead_time.pick_blanket_order)."""
	result = {}
	for item_code, candidates in get_active_blanket_orders(company, on_date).items():
		picked = pick_blanket_order(candidates)
		if picked:
			result[item_code] = picked
	return result


def get_profile_lead_times(company, on_date):
	"""Effective Lead Time Profile values on a date: {(supplier or None, brand or None): days}."""
	if not frappe.db.exists("DocType", "Lead Time Profile"):
		return {}

	rows = frappe.db.sql(
		"""
		select p.name, p.supplier, p.brand, e.from_date, e.lead_time_days, e.idx
		from `tabLead Time Profile` p
		inner join `tabLead Time Profile Entry` e on e.parent = p.name and e.parenttype = 'Lead Time Profile'
		where p.company = %(company)s and e.from_date <= %(on_date)s
		order by e.from_date, e.idx
		""",
		dict(company=company, on_date=getdate(on_date)),
		as_dict=True,
	)
	result = {}
	for row in rows:
		# Ordered by date: the last row per profile is the effective one.
		result[(row.supplier or None, row.brand or None)] = cint(row.lead_time_days)
	return result


def get_lead_time_samples(company, from_date, to_date):
	"""[(supplier, brand or None, days)]: one sample per Purchase Order and item
	brand, from the PO date to the first submitted (non-return) receipt in the period."""
	rows = frappe.db.sql(
		"""
		select po.supplier, i.brand, datediff(min(pr.posting_date), po.transaction_date) as days
		from `tabPurchase Receipt Item` pri
		inner join `tabPurchase Receipt` pr on pr.name = pri.parent
		inner join `tabPurchase Order` po on po.name = pri.purchase_order
		inner join `tabItem` i on i.name = pri.item_code
		where pr.docstatus = 1
			and ifnull(pr.is_return, 0) = 0
			and pr.company = %(company)s
			and po.docstatus = 1
			and pr.posting_date between %(from_date)s and %(to_date)s
		group by po.name, po.supplier, po.transaction_date, i.brand
		""",
		dict(company=company, from_date=from_date, to_date=to_date),
	)
	return [(supplier, brand or None, cint(days)) for supplier, brand, days in rows]


def get_approved_parameters(company):
	"""(run name, {item_code: {...}}) of the active approved Reorder Parameter Run, or (None, {})."""
	if not frappe.db.exists("DocType", "Reorder Parameter Run"):
		return None, {}

	run = frappe.db.get_value(
		"Reorder Parameter Run",
		{"company": company, "docstatus": 1, "is_active": 1},
		"name",
		order_by="analysis_date desc, modified desc",
	)
	if not run:
		return None, {}

	rows = frappe.get_all(
		"Reorder Parameter Line",
		filters={"run": run},
		fields=[
			"item_code",
			"safety_stock",
			"reorder_level",
			"target_stock",
			"supplier",
			"supplier_source",
			"lead_time_days",
			"lead_time_source",
		],
	)
	return run, {row.item_code: row for row in rows}


def _item_conditions(params):
	conditions = ["i.disabled = 0", "i.is_stock_item = 1", "i.has_variants = 0"]
	if params.get("item_code"):
		conditions.append("i.name = %(item_code)s")
	if params.get("item_group"):
		conditions.append(
			"""i.item_group in (
				select ig.name from `tabItem Group` ig
				where ig.lft >= %(ig_lft)s and ig.rgt <= %(ig_rgt)s
			)"""
		)
	return " and ".join(conditions)


def _has_field(doctype, fieldname):
	return frappe.get_meta(doctype).has_field(fieldname)


def get_back_to_back_sales_order_lines(filters):
	"""Lines of submitted Sales Orders that need sourcing or have a Purchase Order
	line (not cancelled) raised against them, limited to Sales Orders the user may read.

	filters: company, sales_order, customer, priority, from_date, to_date.
	"""
	conditions = ["so.docstatus = 1", "so.company = %(company)s"]
	if filters.get("sales_order"):
		conditions.append("so.name = %(sales_order)s")
	if filters.get("customer"):
		conditions.append("so.customer = %(customer)s")
	if filters.get("priority"):
		conditions.append("so.priority = %(priority)s")
	if filters.get("from_date"):
		conditions.append("so.transaction_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("so.transaction_date <= %(to_date)s")

	rows = frappe.db.sql(
		f"""
		select
			soi.name, soi.parent as sales_order, soi.idx, so.customer, so.customer_name,
			so.transaction_date, so.priority, so.required_by_date as order_required_by_date,
			so.status as sales_order_status, soi.item_code, soi.item_name, soi.stock_uom,
			soi.stock_qty, soi.conversion_factor, soi.delivered_qty, soi.base_net_rate,
			soi.delivery_date, soi.needs_sourcing, soi.estimated_landed_cost, soi.promised_date,
			soi.sourcing_request, soi.sourcing_request_item
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		where {" and ".join(conditions)}
			and (
				soi.needs_sourcing = 1
				or exists (
					select 1 from `tabPurchase Order Item` poi
					where poi.sales_order_item = soi.name and poi.docstatus < 2
				)
			)
		order by so.transaction_date, so.name, soi.idx
		""",
		filters,
		as_dict=True,
	)

	names = list({row.sales_order for row in rows})
	if not names:
		return []
	allowed = set(
		frappe.get_list("Sales Order", filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	)
	return [row for row in rows if row.sales_order in allowed]


PURCHASE_LINE_KEYS = ("sales_order_item", "material_request_item")


def get_back_to_back_purchase_lines(keys, key_field="sales_order_item"):
	"""Purchase Order lines (draft and submitted) raised against Sales Order
	lines (or Material Request lines), in stock UOM, with their receipts at
	valuation (which includes Landed Cost Vouchers) and, when shipments are
	tracked, shipped quantity and arrival date.

	{key: [rows]}, key being the PO line's key_field.
	"""
	if not keys:
		return {}
	if key_field not in PURCHASE_LINE_KEYS:
		frappe.throw(_("Invalid key {0}").format(key_field))

	shipments = has_shipment_tracking()
	shipment_columns = (
		"ifnull(poi.shipment_quantity, 0) * poi.conversion_factor as shipped_qty, shp.arrival_date"
		if shipments
		else "0 as shipped_qty, null as arrival_date"
	)
	shipment_join = (
		"""left join (
			select psi.name_related as po_item, max(ps.shipment_arriving_date) as arrival_date
			from `tabPurchase Shipment Item` psi
			inner join `tabPurchase Shipment` ps on ps.name = psi.parent
			where ps.docstatus = 1 and ifnull(psi.name_related, '') != ''
			group by psi.name_related
		) shp on shp.po_item = poi.name"""
		if shipments
		else ""
	)

	rows = frappe.db.sql(
		f"""
		select
			poi.name, poi.parent as purchase_order, po.docstatus, po.status, po.supplier,
			po.supplier_name, po.currency, poi.{key_field} as line_key, poi.item_code,
			poi.stock_qty, poi.received_qty * poi.conversion_factor as received_qty,
			poi.base_net_rate / poi.conversion_factor as base_unit_rate,
			coalesce(poi.expected_delivery_date, poi.schedule_date) as expected_date,
			sup.landed_cost_percent,
			ifnull(pr.received_stock_qty, 0) as receipt_qty,
			ifnull(pr.received_value, 0) as receipt_value,
			{shipment_columns}
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		left join `tabSupplier` sup on sup.name = po.supplier
		left join (
			select pri.purchase_order_item, sum(pri.stock_qty) as received_stock_qty,
				sum(pri.stock_qty * pri.valuation_rate) as received_value
			from `tabPurchase Receipt Item` pri
			inner join `tabPurchase Receipt` pr on pr.name = pri.parent
			where pr.docstatus = 1 and pri.purchase_order_item in (
				select linked.name from `tabPurchase Order Item` linked
				where linked.{key_field} in %(items)s
			)
			group by pri.purchase_order_item
		) pr on pr.purchase_order_item = poi.name
		{shipment_join}
		where poi.{key_field} in %(items)s and po.docstatus < 2
		order by po.transaction_date, po.name, poi.idx
		""",
		{"items": list(keys)},
		as_dict=True,
	)

	result = {}
	for row in rows:
		result.setdefault(row.line_key, []).append(row)
	return result


def get_back_to_back_request_lines(filters):
	"""Lines of Back-to-Back Purchase Material Requests (draft and submitted),
	limited to Material Requests the user may read. No customer or selling data.

	filters: company, material_request, sourcing_request, from_date, to_date.
	"""
	conditions = [
		"mr.docstatus < 2",
		"mr.company = %(company)s",
		"mr.material_request_type = 'Purchase'",
		"mr.procurement_type = 'Back-to-Back'",
	]
	if filters.get("material_request"):
		conditions.append("mr.name = %(material_request)s")
	if filters.get("sourcing_request"):
		conditions.append("mri.sourcing_request = %(sourcing_request)s")
	if filters.get("from_date"):
		conditions.append("mr.transaction_date >= %(from_date)s")
	if filters.get("to_date"):
		conditions.append("mr.transaction_date <= %(to_date)s")

	rows = frappe.db.sql(
		f"""
		select
			mri.name, mri.parent as material_request, mri.idx, mr.docstatus as mr_docstatus,
			mr.status as mr_status, mr.transaction_date, mri.item_code, mri.item_name,
			mri.stock_uom, mri.stock_qty, mri.schedule_date, mri.sourcing_request,
			mri.sourcing_request_item, sr.priority
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		left join `tabSourcing Request` sr on sr.name = mri.sourcing_request
		where {" and ".join(conditions)}
		order by mr.transaction_date, mr.name, mri.idx
		""",
		filters,
		as_dict=True,
	)

	names = list({row.material_request for row in rows})
	if not names:
		return []
	allowed = set(
		frappe.get_list("Material Request", filters={"name": ["in", names]}, pluck="name", limit_page_length=0)
	)
	return [row for row in rows if row.material_request in allowed]
