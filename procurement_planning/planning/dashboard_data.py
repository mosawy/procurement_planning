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
from procurement_planning.planning.dashboard_calculations import (
	agreement_drawdown,
	agreement_flags,
	first_of_next_month,
	group_totals,
	risk_by_class,
	slow_suppliers,
	spread_plan_by_month,
	top_items_to_buy,
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
