# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Data for the Planned Purchasing and Back-to-Back dashboard pages.

Each endpoint returns everything one page draws, already summarised. Numbers
that stand for documents come with the document names, so the page can open
the list filtered on them. The planned dashboard reuses the planning analysis
(api.analyse with the approved parameters) and keeps its result in the cache
for ten minutes per company and date; Refresh recalculates.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, getdate, today

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning import data_sources
from procurement_planning.planning.b2b_calculations import purchase_progress, sales_line_cost
from procurement_planning.planning.dashboard_calculations import (
	agreement_drawdown,
	agreement_flags,
	first_of_next_month,
	funnel,
	furthest_stage,
	group_totals,
	is_at_risk,
	margin_percent,
	quarter_range,
	risk_by_class,
	slow_suppliers,
	spread_plan_by_month,
	top_items_to_buy,
	win_rate,
)
from procurement_planning.planning.settings import get_company_settings

CACHE_SECONDS = 600
ABC_CLASSES = ["A", "B", "C", "D", "E", "F", "Non-Moving"]
MAX_LINKED_NAMES = 500
SLOW_SUPPLIER_DAYS = 90


# ---------------------------------------------------------------------------
# Planned purchasing


@frappe.whitelist()
def get_planned_dashboard(company, analysis_date=None, refresh=0):
	frappe.only_for(ALLOWED_ROLES)
	if not company:
		frappe.throw(_("Company is required"))
	on_date = getdate(analysis_date or today())
	key = f"procurement_planning:planned_dashboard:{company}:{on_date}"
	cache = frappe.cache()
	if not cint(refresh):
		cached = cache.get_value(key)
		if cached:
			return cached

	data = _planned_dashboard(company, on_date)
	cache.set_value(key, data, expires_in_sec=CACHE_SECONDS)
	return data


def _planned_dashboard(company, on_date):
	from procurement_planning.planning import api

	settings = api.get_settings(company, analysis_date=on_date)
	results = api.analyse(settings, use_approved=True)
	company_settings = get_company_settings(company)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")

	rows = [
		{
			"item_code": r.item_code,
			"item_name": r.item_name,
			"supplier": r.supplier,
			"abc_class": r.abc_class,
			"current_stock": r.current_stock,
			"suggested_purchase": r.proposed["suggested_purchase"],
			"suggested_value": r.suggested_value,
			"stockout_risk": r.proposed["stockout_risk"],
			"below_reorder_level": r.proposed["below_reorder_level"],
			"warnings": r.proposed["warnings"],
		}
		for r in results
	]
	buying = [row for row in rows if row["suggested_purchase"] > 0]

	return {
		"company": company,
		"currency": company_currency,
		"analysis_date": str(on_date),
		"generated_at": str(frappe.utils.now_datetime()),
		"kpis": {
			"total_items": len(rows),
			"below_reorder": sum(1 for row in rows if row["below_reorder_level"]),
			"high_risk": sum(1 for row in rows if row["stockout_risk"] == "High"),
			"suggested_value": sum(row["suggested_value"] for row in buying),
			"items_to_buy": len(buying),
			"no_supplier": sum(1 for row in rows if "NO_SUPPLIER" in row["warnings"]),
			"no_lead_time": sum(1 for row in rows if "LEAD_TIME_FALLBACK" in row["warnings"]),
			"late_pos": get_late_purchase_orders(company, on_date, company_settings.late_po_tolerance_days),
			"in_transit": get_in_transit(company),
		},
		"active_run": get_active_run(company, on_date),
		"blanket_orders": get_blanket_order_status(company, on_date),
		"charts": {
			"by_supplier": group_totals(buying, "supplier", "suggested_value", limit=10),
			"risk_by_class": {"classes": ABC_CLASSES, "values": risk_by_class(rows, ABC_CLASSES)},
			"plan_vs_actual": get_plan_vs_actual(company, on_date),
		},
		"top_items": top_items_to_buy(rows),
		"alerts": {
			"old_requests": get_old_purchase_requests(company, on_date, company_settings.pending_mr_max_age_days),
			"slow_suppliers": slow_suppliers(
				data_sources.get_lead_time_samples(company, add_days(on_date, -SLOW_SUPPLIER_DAYS), on_date),
				data_sources.get_profile_lead_times(company, on_date),
			),
		},
	}


def get_late_purchase_orders(company, on_date, tolerance_days):
	"""Open planned-purchase PO lines expected before on_date - tolerance: count
	of Purchase Orders and the value still to receive. Back-to-back lines and
	drop-ship lines are left out, as in planning."""
	expected = "coalesce(poi.expected_delivery_date, poi.schedule_date)"
	if frappe.get_meta("Purchase Order").has_field("expected_delivery_date"):
		expected = "coalesce(po.expected_delivery_date, poi.expected_delivery_date, poi.schedule_date)"
	rows = frappe.db.sql(
		f"""
		select po.name, sum((poi.qty - poi.received_qty) * poi.base_net_rate) as open_value
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1
			and po.company = %(company)s
			and po.status not in ('Closed', 'Completed', 'Delivered', 'On Hold')
			and poi.received_qty < poi.qty
			and ifnull(poi.sales_order, '') = ''
			and ifnull(poi.delivered_by_supplier, 0) = 0
			and {expected} < %(cutoff)s
		group by po.name
		order by open_value desc
		""",
		{"company": company, "cutoff": add_days(on_date, -cint(tolerance_days))},
		as_dict=True,
	)
	return {
		"count": len(rows),
		"value": sum(flt(row.open_value) for row in rows),
		"names": [row.name for row in rows][:MAX_LINKED_NAMES],
		"tolerance_days": cint(tolerance_days),
	}


def get_in_transit(company):
	"""Quantity shipped on Purchase Shipments and not yet received (stock UOM),
	with its value; None without shipment tracking."""
	if not data_sources.has_shipment_tracking():
		return None
	rows = frappe.db.sql(
		"""
		select po.name,
			sum((poi.shipment_quantity - poi.received_qty) * poi.conversion_factor) as qty,
			sum((poi.shipment_quantity - poi.received_qty) * poi.base_net_rate) as value
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1
			and po.company = %(company)s
			and po.status not in ('Closed', 'Completed', 'Delivered')
			and ifnull(poi.shipment_quantity, 0) > poi.received_qty
		group by po.name
		""",
		{"company": company},
		as_dict=True,
	)
	return {
		"qty": sum(flt(row.qty) for row in rows),
		"value": sum(flt(row.value) for row in rows),
		"names": [row.name for row in rows][:MAX_LINKED_NAMES],
	}


def get_active_run(company, on_date):
	run = frappe.db.get_value(
		"Reorder Parameter Run",
		{"company": company, "docstatus": 1, "is_active": 1},
		["name", "analysis_date", "total_items", "changed_items", "overridden_items", "last_calculated_on"],
		as_dict=True,
		order_by="analysis_date desc, modified desc",
	)
	next_due = first_of_next_month(on_date)
	if not run:
		return {"name": None, "next_due": str(next_due)}
	run_date = getdate(run.analysis_date)
	run.update(
		{
			"analysis_date": str(run_date),
			"last_calculated_on": str(run.last_calculated_on) if run.last_calculated_on else None,
			"next_due": str(next_due),
			# A run for an earlier month than the dashboard date is due again.
			"overdue": (run_date.year, run_date.month) < (on_date.year, on_date.month),
		}
	)
	return run


def get_blanket_order_status(company, on_date):
	"""Purchasing agreements valid on on_date with their drawdown by value (company currency)."""
	agreements = {}
	for candidates in data_sources.get_active_blanket_orders(company, on_date).values():
		for c in candidates:
			agreement = agreements.setdefault(
				c["blanket_order"],
				{
					"blanket_order": c["blanket_order"],
					"supplier": c["supplier"],
					"currency": c["currency"],
					"to_date": c["to_date"],
					"lines": [],
					"no_exchange_rate": False,
				},
			)
			if c["base_rate"] is None:
				agreement["no_exchange_rate"] = True
			agreement["lines"].append((c["qty"], c["ordered_qty"], c["base_rate"] or 0))

	result = []
	for agreement in agreements.values():
		planned, ordered, percent = agreement_drawdown(agreement.pop("lines"))
		agreement.update(
			{
				"planned_value": planned,
				"ordered_value": ordered,
				"percent": percent,
				"flags": agreement_flags(agreement["to_date"], percent, on_date),
				"days_left": (agreement["to_date"] - on_date).days,
				"to_date": str(agreement["to_date"]),
			}
		)
		result.append(agreement)
	result.sort(key=lambda a: (-len(a["flags"]), a["to_date"], a["blanket_order"]))
	return result


def get_plan_vs_actual(company, on_date):
	"""Per month of on_date's year: value of planned-purchase PO lines (company
	currency, back-to-back lines left out) and the Blanket Order plan spread
	evenly over each agreement's months, converted on on_date."""
	year = on_date.year
	actual = {month: 0.0 for month in range(1, 13)}
	for month, value in frappe.db.sql(
		"""
		select month(po.transaction_date), sum(poi.base_net_amount)
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and po.company = %(company)s and year(po.transaction_date) = %(year)s
			and ifnull(poi.sales_order, '') = ''
		group by month(po.transaction_date)
		""",
		{"company": company, "year": year},
	):
		actual[cint(month)] = flt(value)

	rows = frappe.db.sql(
		"""
		select bo.name, bo.from_date, bo.to_date, sup.default_currency as currency,
			sum(boi.qty * boi.rate) as value
		from `tabBlanket Order` bo
		inner join `tabBlanket Order Item` boi on boi.parent = bo.name and boi.parenttype = 'Blanket Order'
		left join `tabSupplier` sup on sup.name = bo.supplier
		where bo.blanket_order_type = 'Purchasing' and bo.docstatus = 1 and bo.company = %(company)s
			and year(bo.from_date) <= %(year)s and year(bo.to_date) >= %(year)s
		group by bo.name, bo.from_date, bo.to_date, sup.default_currency
		""",
		{"company": company, "year": year},
		as_dict=True,
	)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	rates = data_sources.get_exchange_rates(
		{row.currency or company_currency for row in rows}, company_currency, on_date
	)
	agreements = [
		{
			"from_date": getdate(row.from_date),
			"to_date": getdate(row.to_date),
			"value": flt(row.value) * (rates.get(row.currency or company_currency) or 0),
		}
		for row in rows
	]
	plan = spread_plan_by_month(agreements, year)
	return {
		"year": year,
		"actual": [actual[m] for m in range(1, 13)],
		"plan": [plan[m] for m in range(1, 13)],
		"has_plan": bool(rows),
		"missing_exchange_rate": any(not rates.get(row.currency or company_currency) for row in rows),
	}


def get_old_purchase_requests(company, on_date, max_age_days):
	"""Open planned Purchase Material Requests older than the pending age limit."""
	if not cint(max_age_days):
		return None
	names = frappe.db.sql_list(
		"""
		select mr.name
		from `tabMaterial Request` mr
		where mr.docstatus = 1 and mr.company = %(company)s
			and mr.material_request_type = 'Purchase'
			and ifnull(mr.procurement_type, '') != 'Back-to-Back'
			and mr.status not in ('Stopped', 'Closed')
			and ifnull(mr.per_ordered, 0) < 100
			and mr.transaction_date < %(cutoff)s
		order by mr.transaction_date
		""",
		{"company": company, "cutoff": add_days(on_date, -cint(max_age_days))},
	)
	return {"count": len(names), "names": names[:MAX_LINKED_NAMES], "max_age_days": cint(max_age_days)}


# ---------------------------------------------------------------------------
# Back-to-back

B2B_PAGE = "back-to-back-dashboard"
LATE_LINES_LIMIT = 15


@frappe.whitelist()
def get_back_to_back_dashboard(company, from_date=None, to_date=None):
	"""Back-to-back funnel, KPIs, margin and supplier charts and late lines.
	Shows cost and margin: only for users the page is open to (management)."""
	if not frappe.get_doc("Page", B2B_PAGE).is_permitted():
		frappe.throw(_("Not permitted"), frappe.PermissionError)
	if not company:
		frappe.throw(_("Company is required"))

	on_date = getdate(today())
	default_from, default_to = quarter_range(on_date)
	from_date = getdate(from_date) if from_date else default_from
	to_date = getdate(to_date) if to_date else default_to
	settings = get_company_settings(company)
	company_currency = frappe.get_cached_value("Company", company, "default_currency")
	period = {"company": company, "from_date": from_date, "to_date": to_date}

	late_lines = get_late_lines(company, on_date)
	return {
		"company": company,
		"currency": company_currency,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"funnel": get_funnel(period),
		"kpis": {
			"turnaround": get_sourcing_turnaround(period),
			"late": {
				"late": sum(1 for row in late_lines if row["late"]),
				"at_risk": sum(1 for row in late_lines if not row["late"]),
				"names": sorted({row["sales_order"] for row in late_lines})[:MAX_LINKED_NAMES],
			},
			"expiring_offers": get_expiring_offers(company, on_date),
			"sales": get_back_to_back_sales(period),
			"excess": get_excess_to_stock(period),
		},
		"charts": {
			"margin_by_month": get_margin_by_month(period, settings, company_currency),
			"top_suppliers": get_top_back_to_back_suppliers(period),
		},
		"late_lines": late_lines[:LATE_LINES_LIMIT],
		"late_lines_total": len(late_lines),
	}


def get_funnel(period):
	"""Funnel of the quotations with sourcing lines dated in the period, each
	counted up to the furthest stage it reached; plus the live number of
	Sourcing Requests waiting for offers and ready to submit."""
	quotations = frappe.db.sql(
		"""
		select q.name, q.docstatus
		from `tabQuotation` q
		where q.company = %(company)s and q.docstatus < 2
			and q.transaction_date between %(from_date)s and %(to_date)s
			and exists (
				select 1 from `tabQuotation Item` qi where qi.parent = q.name and qi.needs_sourcing = 1
			)
		""",
		period,
		as_dict=True,
	)
	names = [q.name for q in quotations]
	stages_by_quotation = {}
	if names:
		values = {"names": names}
		sent = dict(
			frappe.db.sql(
				"""select quotation, max(docstatus) from `tabSourcing Request`
				where quotation in %(names)s and docstatus < 2 group by quotation""",
				values,
			)
		)
		orders = frappe.db.sql(
			"""
			select distinct soi.prevdoc_docname as quotation, so.name, so.per_delivered
			from `tabSales Order Item` soi
			inner join `tabSales Order` so on so.name = soi.parent
			where so.docstatus = 1 and soi.prevdoc_docname in %(names)s
			""",
			values,
			as_dict=True,
		)
		order_progress = _order_progress([o.name for o in orders])
		by_quotation = {}
		for order in orders:
			by_quotation.setdefault(order.quotation, []).append(order)

		for q in quotations:
			q_orders = by_quotation.get(q.name, [])
			progress = [order_progress.get(o.name, {}) for o in q_orders]
			flags = [
				True,
				q.name in sent,
				cint(sent.get(q.name)) == 1,
				q.docstatus == 1,
				bool(q_orders),
				any(p.get("requested") for p in progress),
				any(p.get("ordered") for p in progress),
				bool(progress) and all(p.get("received") for p in progress),
				bool(q_orders) and all(flt(o.per_delivered) >= 100 for o in q_orders),
			]
			stages_by_quotation[q.name] = furthest_stage(flags)

	rows = funnel(list(stages_by_quotation.values()))
	for index, row in enumerate(rows):
		row["names"] = [name for name, stage in stages_by_quotation.items() if stage >= index][:MAX_LINKED_NAMES]

	live = dict(
		frappe.db.sql(
			"""select status, count(*) from `tabSourcing Request`
			where company = %(company)s and docstatus = 0 group by status""",
			period,
		)
	)
	submitted = rows[3]["count"]
	won = rows[4]["count"]
	return {
		"stages": rows,
		"win_rate": win_rate(submitted, won),
		"waiting": cint(live.get("Waiting for Offers")) + cint(live.get("Draft")),
		"ready": cint(live.get("Ready")),
	}


def _order_progress(sales_orders):
	"""{sales order: {requested, ordered, received}} over its sourced lines."""
	if not sales_orders:
		return {}
	values = {"orders": sales_orders}
	requested = set(
		frappe.db.sql_list(
			"""
			select distinct mri.sales_order
			from `tabMaterial Request Item` mri
			inner join `tabMaterial Request` mr on mr.name = mri.parent
			where mr.docstatus < 2 and mr.procurement_type = 'Back-to-Back' and mri.sales_order in %(orders)s
			""",
			values,
		)
	)
	lines = frappe.db.sql(
		"""
		select soi.parent, soi.stock_qty,
			(select ifnull(sum(poi.stock_qty), 0) from `tabPurchase Order Item` poi
				where poi.sales_order_item = soi.name and poi.docstatus = 1) as ordered_qty,
			(select ifnull(sum(poi.received_qty * poi.conversion_factor), 0) from `tabPurchase Order Item` poi
				where poi.sales_order_item = soi.name and poi.docstatus = 1) as received_qty
		from `tabSales Order Item` soi
		where soi.parent in %(orders)s and soi.needs_sourcing = 1
		""",
		values,
		as_dict=True,
	)
	result = {}
	for line in lines:
		progress = result.setdefault(line.parent, {"ordered": False, "received": True})
		progress["ordered"] = progress["ordered"] or flt(line.ordered_qty) > 0
		progress["received"] = progress["received"] and flt(line.received_qty) >= flt(line.stock_qty) - 1e-9
	for order in sales_orders:
		progress = result.setdefault(order, {"ordered": False, "received": False})
		progress["requested"] = order in requested
	return result


def get_sourcing_turnaround(period):
	"""Average days from creating a Sourcing Request to submitting it, for those submitted in the period."""
	rows = frappe.db.sql(
		"""
		select name, timestampdiff(minute, creation, submitted_on) / 1440 as days
		from `tabSourcing Request`
		where company = %(company)s and docstatus = 1 and submitted_on is not null
			and date(submitted_on) between %(from_date)s and %(to_date)s
		""",
		period,
		as_dict=True,
	)
	return {
		"days": sum(flt(row.days) for row in rows) / len(rows) if rows else None,
		"count": len(rows),
		"names": [row.name for row in rows][:MAX_LINKED_NAMES],
	}


def get_late_lines(company, on_date):
	"""Open sourced Sales Order lines late against the promise (expected arrival
	after the promised date) or at risk (within 7 days of it), latest first."""
	lines = data_sources.get_back_to_back_sales_order_lines(frappe._dict(company=company))
	purchases = data_sources.get_back_to_back_purchase_lines([line.name for line in lines])
	result = []
	for line in lines:
		if not line.promised_date or line.sales_order_status in ("Closed", "Completed"):
			continue
		delivered = flt(line.delivered_qty) * (flt(line.conversion_factor) or 1)
		progress = purchase_progress(
			purchases.get(line.name, []), flt(line.stock_qty), on_date, getdate(line.promised_date), delivered
		)
		days = progress["days_late"]
		if days is None or not (days > 0 or is_at_risk(days)):
			continue
		result.append(
			{
				"sales_order": line.sales_order,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"customer": line.customer_name or line.customer,
				"stage": progress["stage"],
				"promised_date": str(getdate(line.promised_date)),
				"expected_arrival": str(progress["expected_arrival"]) if progress["expected_arrival"] else None,
				"days_late": days,
				"late": days > 0,
			}
		)
	result.sort(key=lambda row: -row["days_late"])
	return result


def get_expiring_offers(company, on_date):
	"""Chosen offers on draft Sourcing Requests that expire within 7 days."""
	rows = frappe.db.sql(
		"""
		select distinct sr.name
		from `tabSourcing Request Item` sri
		inner join `tabSourcing Request` sr on sr.name = sri.parent
		where sr.company = %(company)s and sr.docstatus = 0
			and ifnull(sri.supplier_quotation_item, '') != ''
			and sri.valid_till between %(from_date)s and %(to_date)s
		""",
		{"company": company, "from_date": on_date, "to_date": add_days(on_date, 7)},
	)
	lines = frappe.db.sql(
		"""
		select count(*)
		from `tabSourcing Request Item` sri
		inner join `tabSourcing Request` sr on sr.name = sri.parent
		where sr.company = %(company)s and sr.docstatus = 0
			and ifnull(sri.supplier_quotation_item, '') != ''
			and sri.valid_till between %(from_date)s and %(to_date)s
		""",
		{"company": company, "from_date": on_date, "to_date": add_days(on_date, 7)},
	)[0][0]
	return {"lines": cint(lines), "names": [row[0] for row in rows]}


def get_back_to_back_sales(period):
	"""Sourced lines of Sales Orders submitted in the period: sales value and
	quoted gross margin (cost = estimated_landed_cost, the cost the price was built on)."""
	rows = frappe.db.sql(
		"""
		select so.name, sum(soi.base_net_amount) as sales,
			sum(soi.estimated_landed_cost * soi.stock_qty) as cost
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		where so.docstatus = 1 and so.company = %(company)s and soi.needs_sourcing = 1
			and so.transaction_date between %(from_date)s and %(to_date)s
		group by so.name
		""",
		period,
		as_dict=True,
	)
	sales = sum(flt(row.sales) for row in rows)
	cost = sum(flt(row.cost) for row in rows)
	return {
		"value": sales,
		"margin": margin_percent(sales, cost),
		"orders": len(rows),
		"names": [row.name for row in rows][:MAX_LINKED_NAMES],
	}


def get_excess_to_stock(period):
	"""Supplier minimum excess bought into stock on back-to-back Purchase Orders submitted in the period."""
	rows = frappe.db.sql(
		"""
		select po.name, sum(poi.stock_qty) as qty, sum(poi.base_net_amount) as value
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and po.company = %(company)s and poi.is_excess = 1
			and po.transaction_date between %(from_date)s and %(to_date)s
		group by po.name
		""",
		period,
		as_dict=True,
	)
	return {
		"qty": sum(flt(row.qty) for row in rows),
		"value": sum(flt(row.value) for row in rows),
		"names": [row.name for row in rows][:MAX_LINKED_NAMES],
	}


def get_margin_by_month(period, settings, company_currency):
	"""Per month of the period: quoted margin of sourced Sales Order lines (cost
	the price was built on) and actual margin (lines with Purchase Orders:
	received cost where received, else the PO cost with landed %, as in the
	Back-to-Back Order Cost report)."""
	lines = frappe.db.sql(
		"""
		select soi.name, date_format(so.transaction_date, '%%Y-%%m') as month, soi.base_net_amount,
			soi.estimated_landed_cost * soi.stock_qty as quoted_cost, soi.stock_qty
		from `tabSales Order Item` soi
		inner join `tabSales Order` so on so.name = soi.parent
		where so.docstatus = 1 and so.company = %(company)s and soi.needs_sourcing = 1
			and so.transaction_date between %(from_date)s and %(to_date)s
		""",
		period,
		as_dict=True,
	)
	purchases = data_sources.get_back_to_back_purchase_lines([line.name for line in lines])
	months = {}
	for line in lines:
		month = months.setdefault(line.month, {"sales": 0, "quoted_cost": 0, "actual_sales": 0, "actual_cost": 0})
		sales = flt(line.base_net_amount)
		month["sales"] += sales
		month["quoted_cost"] += flt(line.quoted_cost)
		_qty, unit_cost = sales_line_cost(
			purchases.get(line.name, []),
			settings.default_landed_cost_percent,
			settings.fx_buffer_percent,
			company_currency,
		)
		if unit_cost is not None:
			month["actual_sales"] += sales
			month["actual_cost"] += unit_cost * flt(line.stock_qty)

	labels = _months_between(getdate(period["from_date"]), getdate(period["to_date"]))
	return {
		"labels": labels,
		"quoted": [margin_percent(months[m]["sales"], months[m]["quoted_cost"]) if m in months else None for m in labels],
		"actual": [
			margin_percent(months[m]["actual_sales"], months[m]["actual_cost"]) if m in months else None for m in labels
		],
	}


def _months_between(from_date, to_date):
	months, year, month = [], from_date.year, from_date.month
	while (year, month) <= (to_date.year, to_date.month):
		months.append(f"{year}-{month:02d}")
		year, month = (year + 1, 1) if month == 12 else (year, month + 1)
	return months


def get_top_back_to_back_suppliers(period, limit=10):
	"""Suppliers by value of back-to-back Purchase Order lines (customer lines
	and their supplier minimum excess) submitted in the period."""
	rows = frappe.db.sql(
		"""
		select po.supplier, sum(poi.base_net_amount) as value
		from `tabPurchase Order Item` poi
		inner join `tabPurchase Order` po on po.name = poi.parent
		where po.docstatus = 1 and po.company = %(company)s
			and po.transaction_date between %(from_date)s and %(to_date)s
			and (ifnull(poi.sales_order, '') != '' or poi.is_excess = 1)
		group by po.supplier
		order by value desc
		limit %(limit)s
		""",
		dict(period, limit=limit),
		as_dict=True,
	)
	return [(row.supplier, flt(row.value)) for row in rows]
