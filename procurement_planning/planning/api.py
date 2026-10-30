# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""API for the Procurement Planning page.

Combines the data sources with the SAP and proposed calculation engines. The
analysis itself is read-only; create_material_request and derive_lead_times
are the only calls that write.
"""

import frappe
from frappe import _
from frappe.utils import add_days, add_months, cint, flt, get_first_day, getdate, today

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning import data_sources
from procurement_planning.planning.demand_history import (
	count_stockout_days,
	opening_balance,
	select_demand_months,
	stockout_months,
)
from procurement_planning.planning.lead_time import resolve_lead_time, resolve_supplier
from procurement_planning.planning.proposed_calculations import (
	FALLBACK_LEAD_TIME_DAYS,
	MISSING_DATA_WARNINGS,
	WARNING_LABELS,
	calculate_proposed,
	split_purchase_orders,
)
from procurement_planning.planning.sap_calculations import (
	NON_MOVING_CLASS,
	SAP_PERIOD_MONTHS,
	SAP_SAFETY_DAYS,
	calculate_sap,
	classify_abc,
	count_months_with_sales,
)
from procurement_planning.planning.settings import get_company_settings

SUPPLIER_APPROVED_RUN = "Approved Run"
LEAD_TIME_APPROVED_RUN = "Approved Run"


@frappe.whitelist()
def get_company_defaults(company):
	"""Filter defaults for the planning page from the company settings."""
	frappe.only_for(ALLOWED_ROLES)
	settings = get_company_settings(company)
	run, _lines = data_sources.get_approved_parameters(company)
	return {
		"analysis_months": settings.analysis_months,
		"safety_stock_days": settings.safety_stock_days,
		"review_period_days": settings.review_period_days,
		"default_purchase_warehouse": settings.default_purchase_warehouse,
		"settings_exist": settings.exists,
		"approved_run": run,
	}


@frappe.whitelist()
def get_planning_analysis(
	company,
	item_group=None,
	analysis_months=None,
	safety_stock_days=None,
	review_period_days=None,
	analysis_date=None,
	use_approved=1,
):
	frappe.only_for(ALLOWED_ROLES)
	settings = get_settings(
		company, item_group, analysis_months, safety_stock_days, review_period_days, analysis_date=analysis_date
	)
	results = analyse(settings, use_approved=cint(use_approved))

	return {
		"settings": _settings_summary(settings),
		"summary": _dashboard(results),
		"rows": [_table_row(result) for result in results],
		"notes": _notes(settings),
		"warning_labels": _warning_labels(),
		"missing_data_warnings": list(MISSING_DATA_WARNINGS),
	}


@frappe.whitelist()
def get_item_planning_details(
	company,
	item_code,
	item_group=None,
	analysis_months=None,
	safety_stock_days=None,
	review_period_days=None,
	analysis_date=None,
	use_approved=1,
):
	frappe.only_for(ALLOWED_ROLES)
	if not item_code:
		frappe.throw(_("Item Code is required"))

	settings = get_settings(
		company,
		item_group,
		analysis_months,
		safety_stock_days,
		review_period_days,
		item_code=item_code,
		analysis_date=analysis_date,
	)
	results = analyse(settings, include_history=True, use_approved=cint(use_approved))
	if not results:
		frappe.throw(_("Item {0} is not an active stock item in the selected Item Group").format(item_code))

	return {
		"settings": _settings_summary(settings),
		"item": results[0],
		"notes": _notes(settings),
		"warning_labels": _warning_labels(),
	}


@frappe.whitelist()
def derive_lead_times(company):
	frappe.only_for(ALLOWED_ROLES)
	from procurement_planning.planning.lead_time_service import derive_lead_times as derive

	return derive(company)


@frappe.whitelist()
def create_material_request(company, items, warehouse=None):
	"""Create a draft Purchase Material Request from planning rows.

	items: [{item_code, qty, suggested_qty, variance_reason, supplier, schedule_date}].
	qty is in stock UOM. A quantity different from the suggestion needs a
	variance reason.
	"""
	frappe.only_for(ALLOWED_ROLES)
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("Not permitted to create Material Requests"), frappe.PermissionError)

	items = frappe.parse_json(items) or []
	settings = get_company_settings(company)
	warehouse = warehouse or settings.default_purchase_warehouse
	if not warehouse:
		frappe.throw(_("Select a warehouse, or set a Default Purchase Warehouse in Procurement Planning Settings"))

	warehouse_company = frappe.db.get_value("Warehouse", warehouse, "company")
	if warehouse_company != company:
		frappe.throw(_("Warehouse {0} does not belong to Company {1}").format(warehouse, company))

	run, _lines = data_sources.get_approved_parameters(company)
	transaction_date = getdate(today())

	request = frappe.new_doc("Material Request")
	request.update(
		{
			"material_request_type": "Purchase",
			"company": company,
			"transaction_date": transaction_date,
			"procurement_type": "Planned",
			"reorder_parameter_run": run,
			"set_warehouse": warehouse,
		}
	)

	for row in items:
		row = frappe._dict(row)
		qty = flt(row.qty)
		if qty <= 0:
			continue

		suggested = flt(row.suggested_qty)
		differs = abs(qty - suggested) > 1e-9
		if differs and not row.variance_reason:
			frappe.throw(
				_("Item {0}: quantity {1} differs from the suggested {2}. Select a Variance Reason.").format(
					row.item_code, qty, suggested
				)
			)

		item = frappe.get_cached_value(
			"Item", row.item_code, ["item_name", "description", "stock_uom"], as_dict=True
		)
		if not item:
			frappe.throw(_("Item {0} does not exist").format(row.item_code))

		schedule_date = getdate(row.schedule_date) if row.schedule_date else add_days(transaction_date, 1)
		request.append(
			"items",
			{
				"item_code": row.item_code,
				"item_name": item.item_name,
				"description": item.description or item.item_name,
				"qty": qty,
				"uom": item.stock_uom,
				"stock_uom": item.stock_uom,
				"conversion_factor": 1,
				"warehouse": warehouse,
				"schedule_date": max(schedule_date, transaction_date),
				"suggested_qty": suggested,
				"variance_reason": row.variance_reason if differs else None,
				"suggested_supplier": row.supplier or None,
			},
		)

	if not request.get("items"):
		frappe.throw(_("No item with a quantity above zero"))

	request.insert()
	return request.name


def get_settings(
	company,
	item_group=None,
	analysis_months=None,
	safety_stock_days=None,
	review_period_days=None,
	item_code=None,
	analysis_date=None,
):
	company_settings = get_company_settings(company)
	if analysis_months in (None, ""):
		analysis_months = company_settings.analysis_months

	params = data_sources.build_query_params(company, item_group, analysis_months, item_code, analysis_date)
	abc_from, abc_to = data_sources.get_analysis_period(SAP_PERIOD_MONTHS, params.analysis_date)

	return frappe._dict(
		params=params,
		analysis_months=len(month_keys(params.from_date, params.to_date)),
		safety_stock_days=_non_negative_int(
			safety_stock_days, company_settings.safety_stock_days, _("Safety Stock Days")
		),
		review_period_days=_non_negative_int(
			review_period_days, company_settings.review_period_days, _("Review Period Days")
		),
		abc_from=abc_from,
		abc_to=abc_to,
		analysis_date=params.analysis_date,
		company_settings=company_settings,
		stockout_ratio=company_settings.stockout_day_ratio / 100,
		late_po_tolerance_days=company_settings.late_po_tolerance_days,
		exclude_back_to_back=bool(company_settings.exclude_back_to_back),
		default_lead_time_days=company_settings.default_lead_time_days,
	)


def analyse(settings, include_history=False, use_approved=True):
	params = settings.params
	company_settings = settings.company_settings
	sales_from = min(params.from_date, settings.abc_from)

	items = data_sources.get_items(params)
	stock = data_sources.get_stock_balances(params)
	monthly_sales = data_sources.get_monthly_net_sales(params, sales_from, params.to_date)
	movements = data_sources.get_stock_movements(params, params.from_date)
	so_lines = data_sources.get_open_sales_order_lines(params)
	po_lines = data_sources.get_open_purchase_orders_by_date(params)
	pending_pr = data_sources.get_pending_purchase_requests(params, company_settings.pending_mr_max_age_days)
	supplier_sources = data_sources.get_item_supplier_sources(params, company_settings.supplier_history_months)
	profile_lead_times = data_sources.get_profile_lead_times(params.company, settings.analysis_date)
	approved_run, approved_lines = (
		data_sources.get_approved_parameters(params.company) if use_approved else (None, {})
	)

	analysis_keys = month_keys(params.from_date, params.to_date)
	abc_keys = month_keys(settings.abc_from, settings.abc_to)
	history_keys = month_keys(sales_from, params.to_date)

	results = []
	for item_code, item in items.items():
		months = monthly_sales.get(item_code, {})
		item_stock = stock.get(item_code) or {}
		current_stock = flt(item_stock.get("current_stock"))

		# Demand: completed months since the item started, without stock-out months.
		item_movements = movements.get(item_code, [])
		stockout_days = count_stockout_days(
			opening_balance(current_stock, item_movements), item_movements, analysis_keys
		)
		stockout_keys = stockout_months(stockout_days, settings.stockout_ratio)
		eligible = eligible_month_keys(analysis_keys, history_keys, item.creation, months)
		used_keys, net_sales, excluded_keys, all_months_stockout = select_demand_months(
			eligible, stockout_keys, months
		)

		months_with_sales = count_months_with_sales(months.get(key, 0) for key in abc_keys)
		abc_class = classify_abc(months_with_sales)
		net_sales_12m = sum(months.get(key, 0) for key in abc_keys)
		net_sales_all_months = sum(months.get(key, 0) for key in analysis_keys)

		# Supplier and lead time.
		approved = approved_lines.get(item_code)
		sources = supplier_sources.get(item_code) or {}
		supplier, supplier_source = resolve_supplier(
			sources.get("item_default"), sources.get("item_supplier"), sources.get("last_po")
		)
		if approved and approved.supplier:
			# Keep where the run's supplier came from: approving a run does not verify an inferred supplier.
			supplier, supplier_source = approved.supplier, approved.supplier_source or SUPPLIER_APPROVED_RUN

		lead_time, lead_time_source, lead_time_profile = resolve_lead_time(
			cint(item.lead_time_days),
			supplier,
			item.brand,
			profile_lead_times,
			settings.default_lead_time_days,
		)
		if approved and cint(approved.lead_time_days) > 0 and cint(approved.lead_time_days) != cint(lead_time):
			# The run was approved with another lead time: plan with the approved one.
			lead_time, lead_time_source, lead_time_profile = cint(approved.lead_time_days), LEAD_TIME_APPROVED_RUN, None

		effective_lead_time = lead_time or FALLBACK_LEAD_TIME_DAYS
		horizon_end = getdate(add_days(settings.analysis_date, effective_lead_time + settings.review_period_days))

		# Open Sales Orders: back-to-back lines are covered by their own purchase.
		so_due = so_future = so_back_to_back = 0
		for delivery_date, qty, is_back_to_back in so_lines.get(item_code, []):
			if is_back_to_back and settings.exclude_back_to_back:
				so_back_to_back += qty
			elif delivery_date is None or delivery_date <= horizon_end:
				so_due += qty
			else:
				so_future += qty

		# Open Purchase Orders: back-to-back lines are reserved for their customer.
		planning_po_lines = []
		po_back_to_back = 0
		for expected_date, qty, in_transit, is_back_to_back in po_lines.get(item_code, []):
			if is_back_to_back and settings.exclude_back_to_back:
				po_back_to_back += qty
			else:
				planning_po_lines.append((expected_date, qty, in_transit))
		po_qty = sum(line[1] for line in planning_po_lines)
		po_dates = [line[0] for line in planning_po_lines if line[0]]
		po_buckets = split_purchase_orders(
			planning_po_lines, settings.analysis_date, horizon_end, settings.late_po_tolerance_days
		)

		# SAP Grace Days is unverified: assumed to be the lead time used for planning.
		grace_days = lead_time if lead_time and lead_time > 0 else None
		sap = calculate_sap(
			net_sales_12m,
			months_with_sales,
			current_stock,
			po_qty,
			so_due + so_future,
			abc_class,
			grace_days=grace_days,
			pr_foreign=None,
		)

		pending_pr_qty = flt((pending_pr.get(item_code) or {}).get("pending_pr_qty"))
		proposed = calculate_proposed(
			net_sales=net_sales,
			eligible_months=len(used_keys),
			analysis_months=settings.analysis_months,
			is_non_moving=abc_class == NON_MOVING_CLASS,
			lead_time_days=lead_time,
			lead_time_source=lead_time_source,
			safety_stock_days=settings.safety_stock_days,
			review_period_days=settings.review_period_days,
			stock=current_stock,
			open_so=so_due,
			open_so_future=so_future,
			po_buckets=po_buckets,
			min_order_qty=flt(item.min_order_qty),
			order_multiple=flt(item.order_multiple),
			stockout_months_excluded=len(excluded_keys),
			all_months_stockout=all_months_stockout,
			pending_requests=pending_pr_qty,
			approved=(
				{
					"safety_stock": flt(approved.safety_stock),
					"reorder_level": flt(approved.reorder_level),
					"target_stock": flt(approved.target_stock),
				}
				if approved
				else None
			),
		)
		if not supplier:
			proposed["warnings"].append("NO_SUPPLIER")
		elif supplier_source == "Last PO":
			proposed["warnings"].append("SUPPLIER_INFERRED")

		last_purchase_rate = flt(item.last_purchase_rate)
		result = frappe._dict(
			item_code=item_code,
			item_name=item.item_name,
			sap_code=item.sap_code,
			stock_uom=item.stock_uom,
			brand=item.brand,
			item_creation=getdate(item.creation) if item.creation else None,
			item_lead_time_days=cint(item.lead_time_days),
			lead_time_days=lead_time,
			lead_time_source=lead_time_source,
			lead_time_profile=" · ".join(part for part in lead_time_profile if part) if lead_time_profile else None,
			supplier=supplier,
			supplier_source=supplier_source,
			grace_days=grace_days,
			min_order_qty=flt(item.min_order_qty),
			order_multiple=flt(item.order_multiple),
			item_safety_stock=flt(item.safety_stock),
			last_purchase_rate=last_purchase_rate,
			suggested_value=proposed["suggested_purchase"] * last_purchase_rate,
			current_stock=current_stock,
			reservation_stock=flt(item_stock.get("reservation_stock")),
			transit_stock=flt(item_stock.get("transit_stock")),
			net_sales=net_sales,
			net_sales_all_months=net_sales_all_months,
			net_sales_12m=net_sales_12m,
			months_with_sales=months_with_sales,
			abc_class=abc_class,
			eligible_months=len(used_keys),
			stockout_months=excluded_keys,
			open_so=so_due + so_future,
			open_so_due=so_due,
			open_so_future=so_future,
			back_to_back_so=so_back_to_back,
			back_to_back_po=po_back_to_back,
			open_po=po_qty,
			next_expected_po_date=min(po_dates) if po_dates else None,
			horizon_end=horizon_end,
			po_buckets=po_buckets,
			pending_pr=pending_pr_qty,
			approved_run=approved_run if approved else None,
			sap=sap,
			proposed=proposed,
		)
		if include_history:
			result.monthly_history = [
				{
					"month": key,
					"net_sales": months.get(key, 0),
					"in_analysis": key in analysis_keys,
					"in_abc": key in abc_keys,
					"used": key in used_keys,
					"stockout": key in excluded_keys,
					"stockout_days": (stockout_days.get(key) or (0, 0))[0],
					"days": (stockout_days.get(key) or (0, 0))[1],
				}
				for key in history_keys
			]
		results.append(result)

	return results


def month_keys(from_date, to_date):
	"""["YYYY-MM", ...] for every calendar month from from_date to to_date."""
	keys = []
	month = get_first_day(from_date)
	while month <= getdate(to_date):
		keys.append(month.strftime("%Y-%m"))
		month = getdate(add_months(month, 1))
	return keys


def eligible_month_keys(analysis_keys, history_keys, creation, months):
	"""Analysis months from the item's first evidence of existence.

	That is its creation month, or an earlier month with sales movements: items
	migrated with back-dated history can have a creation date after their sales.
	"""
	start = getdate(creation).strftime("%Y-%m") if creation else analysis_keys[0]
	movement_months = [key for key in history_keys if key in months]
	if movement_months:
		start = min(start, movement_months[0])

	return [key for key in analysis_keys if key >= start]


def _non_negative_int(value, default, label):
	if value in (None, ""):
		return default

	try:
		number = float(value)
	except (TypeError, ValueError):
		number = None

	if number is None or number < 0 or not number.is_integer():
		frappe.throw(_("{0} must be zero or a positive whole number").format(label))
	return int(number)


def _table_row(result):
	return {
		"item_code": result.item_code,
		"item_name": result.item_name,
		"abc_class": result.abc_class,
		"supplier": result.supplier,
		"supplier_source": result.supplier_source,
		"lead_time_days": result.lead_time_days,
		"lead_time_source": result.lead_time_source,
		"current_stock": result.current_stock,
		"net_sales": result.net_sales,
		"avg_mon": result.sap["avg_mon"],
		"ams": result.proposed["ams"],
		"below_reorder_level": result.proposed["below_reorder_level"],
		"open_so": result.open_so,
		"open_po": result.open_po,
		"sap_reorder": result.sap["reorder"],
		"sap_max": result.sap["max"],
		"proposed_reorder": result.proposed["reorder_level"],
		"target_stock": result.proposed["target_stock"],
		"suggested_purchase": result.proposed["suggested_purchase"],
		"suggested_value": result.suggested_value,
		"last_purchase_rate": result.last_purchase_rate,
		"stock_uom": result.stock_uom,
		"parameter_source": result.proposed["parameter_source"],
		"stockout_risk": result.proposed["stockout_risk"],
		"warnings": result.proposed["warnings"],
	}


def _dashboard(results):
	return {
		"total_items": len(results),
		"below_reorder_level": sum(1 for r in results if r.proposed["below_reorder_level"]),
		"requiring_purchase": sum(1 for r in results if r.proposed["suggested_purchase"] > 0),
		"total_suggested_purchase": sum(r.proposed["suggested_purchase"] for r in results),
		"total_suggested_value": sum(r.suggested_value for r in results),
		"missing_planning_data": sum(
			1 for r in results if any(w in MISSING_DATA_WARNINGS for w in r.proposed["warnings"])
		),
	}


def _settings_summary(settings):
	company_settings = settings.company_settings
	return {
		"company": settings.params.company,
		"currency": frappe.get_cached_value("Company", settings.params.company, "default_currency"),
		"item_group": settings.params.item_group,
		"analysis_date": settings.analysis_date,
		"analysis_months": settings.analysis_months,
		"analysis_from": settings.params.from_date,
		"analysis_to": settings.params.to_date,
		"abc_from": settings.abc_from,
		"abc_to": settings.abc_to,
		"safety_stock_days": settings.safety_stock_days,
		"review_period_days": settings.review_period_days,
		"late_po_tolerance_days": settings.late_po_tolerance_days,
		"stockout_day_ratio": company_settings.stockout_day_ratio,
		"exclude_back_to_back": settings.exclude_back_to_back,
		"default_lead_time_days": settings.default_lead_time_days,
		"default_purchase_warehouse": company_settings.default_purchase_warehouse,
		"settings_exist": company_settings.exists,
		"fallback_lead_time_days": FALLBACK_LEAD_TIME_DAYS,
		"sap_safety_days": SAP_SAFETY_DAYS,
		"shipment_tracking": bool(data_sources.has_shipment_tracking()),
	}


def _warning_labels():
	return {code: _(label).format(fallback=FALLBACK_LEAD_TIME_DAYS) for code, label in WARNING_LABELS.items()}


def _notes(settings):
	notes = [
		_(
			"Net sales are stock-movement based (Delivery Notes and stock-updating Sales Invoices, net of returns), not accounting net sales."
		),
		_("ABC classes use the fixed last 12 completed months ({0} to {1}), independent of Analysis Months.").format(
			settings.abc_from, settings.abc_to
		),
		_(
			"Months in which the item was out of stock on at least {0}% of days are left out of the average monthly sales."
		).format(flt(settings.company_settings.stockout_day_ratio)),
		_(
			"Lead time comes from the Item, then a Lead Time Profile (supplier + brand, supplier, brand), then the company default ({0} days)."
		).format(settings.default_lead_time_days),
		_(
			"Supplier comes from the Item Default for the company, then Item Supplier, then the latest Purchase Order."
		),
		_(
			"Open POs late by up to {0} days count as supply; later ones are overdue and not counted. Shipped quantities count at their shipment arrival date."
		).format(settings.late_po_tolerance_days),
		_("Open Sales Orders count as demand when due within the planning horizon."),
		_(
			"SAP Grace Days is not verified: it is assumed to equal the lead time used for planning. Without one, SAP Re-Order and Max are unavailable."
		),
		_(
			"SAP PR Foreign has no identified ERPNext source: SAP To Reorder, Rec Qty, Missing SO and To Reorder Final are unavailable."
		),
		_("SAP Min: the class-dependent rule has not been confirmed, so it is unavailable."),
		_("SAP Safety uses a fixed {0} days; the Safety Stock Days filter applies to the proposed calculation only.").format(
			SAP_SAFETY_DAYS
		),
	]
	if settings.exclude_back_to_back:
		notes.append(
			_(
				"Back-to-back orders are left out: Sales Order lines with a Purchase Order raised against them, and those Purchase Order lines."
			)
		)
	if settings.analysis_date != getdate(today()):
		notes.append(
			_(
				"Analysis date {0} is not today: sales history ends at that date, but stock and open orders are as of now."
			).format(settings.analysis_date)
		)
	return notes
