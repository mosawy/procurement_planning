# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Back-to-back purchasing, keeping sales and purchasing data apart.

Quotation (lines marked needs_sourcing) -> Sourcing Request (purchasing: no
customer, no selling rate) -> standard RFQ and Supplier Quotations linked to
its lines -> the chosen offer per line; submitting the Sourcing Request writes
only suggested / minimum rate, promised date, price validity and the cost
(permlevel 1) back to the Quotation lines -> standard Sales Order -> Back-to-
Back Material Request (no customer, no selling rate) -> Purchase Orders at the
chosen offers.

Documents of the other department are created as a system action
(ignore_permissions) after checking the user's permission on the source.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate, today

from procurement_planning.planning.b2b_calculations import (
	EXCESS_CUSTOMER_BEARS,
	EXCESS_TO_STOCK,
	QTY_CHANGE_BLOCK,
	QTY_CHANGE_WARN,
	evaluate_offer,
	line_gross_profit,
	offer_lead_time,
	quotation_rate,
	sourced_qty_change,
	sourcing_status,
)
from procurement_planning.planning.settings import get_company_settings

PROCUREMENT_TYPE = "Back-to-Back"
OTHER_OFFERS_LIMIT = 20
EXCESS_PRICING_OPTIONS = (EXCESS_CUSTOMER_BEARS, EXCESS_TO_STOCK)


# ---------------------------------------------------------------------------
# Supplier offers


def _other_offers(company, item_code, on_date):
	return _offer_rows(
		[
			"sq.company = %(company)s",
			"sqi.item_code = %(item_code)s",
			"(sq.valid_till is null or sq.valid_till >= %(on_date)s)",
		],
		{"company": company, "item_code": item_code, "on_date": on_date},
		limit=OTHER_OFFERS_LIMIT,
	)


def _offer_rows(conditions, values, limit=None):
	return frappe.db.sql(
		f"""
		select
			sqi.name, sqi.parent as supplier_quotation, sqi.item_code, sqi.rate, sqi.base_rate,
			sqi.uom, sqi.conversion_factor, sqi.qty, sqi.lead_time_days,
			sqi.expected_delivery_date, ifnull(sqi.min_order_qty, 0) as min_order_qty,
			sqi.sourcing_request, sqi.sourcing_request_item,
			sq.supplier, sq.supplier_name, sq.currency, sq.transaction_date, sq.valid_till,
			sup.landed_cost_percent
		from `tabSupplier Quotation Item` sqi
		inner join `tabSupplier Quotation` sq on sq.name = sqi.parent
		left join `tabSupplier` sup on sup.name = sq.supplier
		where sq.docstatus = 1 and {" and ".join(conditions)}
		order by sq.transaction_date desc, sq.creation desc
		{f"limit {int(limit)}" if limit else ""}
		""",
		values,
		as_dict=True,
	)


def _evaluate(row, required_qty, on_date, settings, company_currency, excess_pricing, linked=False):
	factor = flt(row.conversion_factor) or 1
	landed_percent = (
		flt(row.landed_cost_percent) if row.landed_cost_percent else settings.default_landed_cost_percent
	)
	offer = {
		"unit_cost": flt(row.base_rate) / factor,
		"min_order_qty": flt(row.min_order_qty) * factor,
		"foreign_currency": row.currency != company_currency,
		"quotation_date": getdate(row.transaction_date) if row.transaction_date else None,
		"lead_time_days": cint(row.lead_time_days),
		"expected_delivery_date": getdate(row.expected_delivery_date) if row.expected_delivery_date else None,
		"valid_till": getdate(row.valid_till) if row.valid_till else None,
	}
	result = evaluate_offer(
		offer,
		required_qty,
		on_date,
		landed_cost_percent=landed_percent,
		fx_buffer_percent=settings.fx_buffer_percent,
		buffer_days=settings.delivery_buffer_days,
		excess_pricing=excess_pricing,
	)
	result.update(
		{
			"supplier_quotation_item": row.name,
			"supplier_quotation": row.supplier_quotation,
			"supplier": row.supplier,
			"supplier_name": row.supplier_name,
			"currency": row.currency,
			"rate": flt(row.rate),
			"uom": row.uom,
			"conversion_factor": factor,
			"offer_qty": flt(row.qty),
			"min_order_qty": offer["min_order_qty"],
			"unit_cost": offer["unit_cost"],
			"landed_cost_percent": landed_percent,
			"foreign_currency": offer["foreign_currency"],
			"valid_till": offer["valid_till"],
			"linked": linked,
		}
	)
	return result


# ---------------------------------------------------------------------------
# Quotation hooks


SOURCING_RESULT_FIELDS = {
	"suggested_rate": 0,
	"minimum_rate": 0,
	"promised_date": None,
	"quote_valid_till": None,
	"sourced_stock_qty": 0,
	"sourced_qty_locked": 0,
	"estimated_landed_cost": 0,
}
SOURCING_LINK_FIELDS = {"sourcing_request": None, "sourcing_request_item": None}


def validate_quotation(doc, method=None):
	"""Keep the sourcing status in line with the lines; cost sourcing lines."""
	if doc.docstatus == 0:
		clear_foreign_sourcing(doc)
	if doc.meta.has_field("sourcing_status"):
		doc.sourcing_status = sourcing_status([d.as_dict() for d in doc.items])
	set_sourcing_valuation(doc)


def clear_foreign_sourcing(doc):
	"""A duplicated quotation copies its lines' sourcing; it belongs to the
	original quotation (or the one this amends), so clear it here."""
	requests = {d.sourcing_request for d in doc.items if d.get("sourcing_request")}
	if not requests:
		return
	owners = dict(
		frappe.get_all(
			"Sourcing Request", filters={"name": ("in", list(requests))}, fields=["name", "quotation"], as_list=True
		)
	)
	own = {doc.name, doc.get("amended_from")} - {None}
	for d in doc.items:
		if d.get("sourcing_request") and owners.get(d.sourcing_request) not in own:
			d.update(dict(SOURCING_RESULT_FIELDS, **SOURCING_LINK_FIELDS))


def validate_sales_order(doc, method=None):
	set_sourcing_valuation(doc)


def set_sourcing_valuation(doc):
	"""Valuation rate and gross profit of sourcing lines from the estimated landed cost.

	ERPNext takes valuation_rate from stock (0 for an item never in stock) and
	recomputes it on every validate (it is in force_item_fields), then sets
	gross_profit in SellingController.validate. doc_events validate runs after
	the controller, so the values set here are the ones saved. Both rates are per
	stock UOM in company currency.
	"""
	for item in doc.items:
		cost = flt(item.get("estimated_landed_cost"))
		if not item.get("needs_sourcing") or cost <= 0:
			continue
		item.valuation_rate = cost
		item.gross_profit = flt(
			line_gross_profit(item.base_rate, item.conversion_factor, cost, item.stock_qty),
			doc.precision("amount", item),
		)


def before_submit_quotation(doc, method=None):
	"""Pricing rules for sourced lines.

	Blocks: a line waiting for purchasing; a quantity above the sourced one (or
	any change when the customer bears the supplier minimum); a rate below the
	minimum rate, unless the user has the settings exception role.
	Warns: a quantity below the sourced one, a price validity that has passed or
	ends before the quotation's, a line without a promised date.
	"""
	lines = [d for d in doc.items if d.get("needs_sourcing")]
	if not lines:
		return

	waiting = [str(d.idx) for d in lines if not flt(d.get("sourced_stock_qty"))]
	if waiting:
		frappe.throw(
			_("Rows {0} are waiting for a price from purchasing (Sourcing Request not submitted yet).").format(
				", ".join(waiting)
			)
		)

	settings = get_company_settings(doc.company)
	blocked, warnings = [], []
	for d in lines:
		change = sourced_qty_change(flt(d.sourced_stock_qty), _stock_qty(d), cint(d.sourced_qty_locked))
		if change == QTY_CHANGE_BLOCK:
			blocked.append(
				_("Row {0}: quantity {1} differs from the sourced {2} {3}; request sourcing again.").format(
					d.idx, _stock_qty(d), flt(d.sourced_stock_qty), d.stock_uom
				)
			)
		elif change == QTY_CHANGE_WARN:
			warnings.append(
				_("Row {0}: quantity is below the sourced {1} {2}; the price was worked out for the larger quantity.").format(
					d.idx, flt(d.sourced_stock_qty), d.stock_uom
				)
			)

	allowed_below = settings.below_minimum_rate_role and settings.below_minimum_rate_role in frappe.get_roles()
	for d in lines:
		minimum = _minimum_line_rate(doc, d, settings)
		if minimum and flt(d.rate) < minimum - 0.005:
			message = _("Row {0}: rate {1} is below the minimum rate {2}.").format(
				d.idx, frappe.format(d.rate, {"fieldtype": "Currency", "options": doc.currency}),
				frappe.format(minimum, {"fieldtype": "Currency", "options": doc.currency}),
			)
			(warnings if allowed_below else blocked).append(message)

	if blocked:
		frappe.throw("<br>".join(blocked), title=_("Cannot submit"))

	on_date = getdate(today())
	for d in lines:
		if d.get("quote_valid_till") and getdate(d.quote_valid_till) < on_date:
			warnings.append(
				_("Row {0}: the price was valid until {1}; check with purchasing.").format(
					d.idx, formatdate(d.quote_valid_till)
				)
			)
		elif d.get("quote_valid_till") and doc.valid_till and getdate(d.quote_valid_till) < getdate(doc.valid_till):
			warnings.append(
				_("Row {0}: the price holds until {1}, before this quotation's validity.").format(
					d.idx, formatdate(d.quote_valid_till)
				)
			)
		if not d.get("promised_date"):
			warnings.append(_("Row {0}: no promised date (the supplier gave no lead time).").format(d.idx))

	if warnings:
		frappe.msgprint("<br>".join(warnings), title=_("Sourced lines"), indicator="orange")


def _minimum_line_rate(doc, line, settings):
	"""Minimum rate per the line's UOM in the quotation currency, from the cost
	(permlevel 1) and the minimum margin, so a later UOM or exchange rate change
	does not move it."""
	cost = flt(line.get("estimated_landed_cost"))
	if cost <= 0:
		return 0
	return quotation_rate(
		cost, settings.minimum_margin_percent, flt(line.conversion_factor) or 1, flt(doc.conversion_rate) or 1
	)


def _stock_qty(line):
	return flt(line.stock_qty) or flt(line.qty) * (flt(line.conversion_factor) or 1)


# ---------------------------------------------------------------------------
# Sales Order -> Purchase Orders


def _schedule_date(line, settings, on_date):
	"""Expected receipt: the promise less the delivery buffer, else the delivery date."""
	if line.get("promised_date"):
		date = add_days(getdate(line.promised_date), -cint(settings.delivery_buffer_days))
	elif line.get("delivery_date"):
		date = getdate(line.delivery_date)
	else:
		date = on_date
	return max(getdate(date), on_date)


def _expected_delivery_date(offer, schedule_date, on_date):
	"""Arrival from the supplier offer: today + its lead time, else the schedule date."""
	lead_time = offer_lead_time(
		getdate(offer.transaction_date) if offer.transaction_date else None,
		cint(offer.lead_time_days),
		getdate(offer.expected_delivery_date) if offer.expected_delivery_date else None,
	)
	if lead_time is None:
		return schedule_date
	return add_days(on_date, lead_time)


def _ordered_sales_order_items(sales_order):
	"""{sales_order_item: purchase_order} for PO lines that are not cancelled."""
	rows = frappe.db.sql(
		"""
		select poi.sales_order_item, poi.parent
		from `tabPurchase Order Item` poi
		where poi.sales_order = %s and poi.docstatus < 2 and ifnull(poi.sales_order_item, '') != ''
		""",
		sales_order,
		as_dict=True,
	)
	return {row.sales_order_item: row.parent for row in rows}


def _material_request_remaining(mr_items):
	"""{material_request_item: stock qty not yet ordered} for submitted Material Requests."""
	mr_items = [d for d in mr_items if d]
	if not mr_items:
		return {}
	rows = frappe.db.sql(
		"""
		select mri.name, mri.stock_qty - mri.ordered_qty as remaining
		from `tabMaterial Request Item` mri
		inner join `tabMaterial Request` mr on mr.name = mri.parent
		where mri.name in %(items)s and mr.docstatus = 1 and mr.status not in ('Stopped', 'Closed')
		""",
		{"items": mr_items},
		as_dict=True,
	)
	return {row.name: flt(row.remaining) for row in rows}

