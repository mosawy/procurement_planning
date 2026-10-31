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
from frappe.desk.doctype.notification_log.notification_log import make_notification_logs
from frappe.utils import add_days, cint, flt, formatdate, getdate, today

from procurement_planning.planning.b2b_calculations import (
	EXCESS_CUSTOMER_BEARS,
	EXCESS_TO_STOCK,
	QTY_CHANGE_BLOCK,
	QTY_CHANGE_WARN,
	evaluate_offer,
	line_gross_profit,
	offer_lead_time,
	purchase_order_split,
	quotation_rate,
	rank_offers,
	sourced_qty_change,
	sourcing_rates,
	sourcing_status,
)
from procurement_planning.planning.settings import get_company_settings

PROCUREMENT_TYPE = "Back-to-Back"
OTHER_OFFERS_LIMIT = 20
EXCESS_PRICING_OPTIONS = (EXCESS_CUSTOMER_BEARS, EXCESS_TO_STOCK)
SOURCING_REQUEST = "Sourcing Request"


# ---------------------------------------------------------------------------
# Quotation -> Sourcing Request


@frappe.whitelist()
def request_sourcing(quotation, items=None):
	"""Send draft Quotation lines to purchasing as a Sourcing Request.

	items: Quotation Item names; empty means every line marked needs_sourcing.
	Lines already on an active (not cancelled) Sourcing Request are skipped.
	The Sourcing Request carries no customer and no selling rate; it is created
	as a system action, since sales cannot read purchasing documents.
	"""
	doc = frappe.get_doc("Quotation", quotation)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Quotation {0} is not a draft").format(doc.name))

	selected = set(frappe.parse_json(items) or [])
	lines = [d for d in doc.items if (d.name in selected if selected else d.needs_sourcing)]
	if not lines:
		frappe.throw(_("Select the items to source, or tick Needs Sourcing on them"))

	active = active_sourcing_lines([d.name for d in lines])
	new_lines = [d for d in lines if d.name not in active]
	if not new_lines:
		frappe.throw(_("The selected items are already with purchasing"))

	settings = get_company_settings(doc.company)
	request = frappe.new_doc(SOURCING_REQUEST)
	request.update(
		{
			"company": doc.company,
			"transaction_date": getdate(today()),
			"required_by_date": doc.get("required_by_date"),
			"priority": doc.get("priority"),
			"margin_percent": settings.default_margin_percent,
			"quotation": doc.name,
		}
	)
	for line in new_lines:
		request.append(
			"items",
			{
				"item_code": line.item_code,
				"item_name": line.item_name,
				"description": line.description or line.item_name,
				"qty": line.qty,
				"uom": line.uom,
				"conversion_factor": flt(line.conversion_factor) or 1,
				"stock_qty": _stock_qty(line),
				"stock_uom": line.stock_uom,
				"quotation_item": line.name,
			},
		)
	request.flags.ignore_permissions = True
	request.insert()

	request_lines = {d.quotation_item: d.name for d in request.items}
	for line in lines:
		line.needs_sourcing = 1
		if line.name in request_lines:
			line.update(dict(SOURCING_RESULT_FIELDS))
			line.sourcing_request = request.name
			line.sourcing_request_item = request_lines[line.name]
	doc.save()
	return {"sourcing_request": request.name, "lines": len(new_lines), "skipped": len(lines) - len(new_lines)}


def active_sourcing_lines(quotation_items):
	"""Quotation Item names on a Sourcing Request that is not cancelled."""
	if not quotation_items:
		return set()
	return set(
		frappe.get_all(
			"Sourcing Request Item",
			filters={"quotation_item": ("in", quotation_items), "docstatus": ("<", 2)},
			pluck="quotation_item",
		)
	)


# ---------------------------------------------------------------------------
# Sourcing Request: evaluation and prices back to the Quotation

OFFER_FIELDS = {
	"supplier_quotation": None,
	"supplier_quotation_item": None,
	"supplier": None,
	"supplier_rate": 0,
	"lead_time_days": 0,
	"min_order_qty": 0,
	"valid_till": None,
	"purchase_qty": 0,
	"excess_qty": 0,
	"landed_cost": 0,
	"pricing_cost": 0,
	"suggested_rate": 0,
	"minimum_rate": 0,
	"promised_date": None,
}


def evaluate_sourcing_line(request, line, settings, company_currency, on_date):
	"""Re-read the line's chosen offer and set its cost, quantities, rates and promise."""
	line.stock_qty = flt(line.qty) * (flt(line.conversion_factor) or 1)
	if not line.supplier_quotation_item:
		line.update(OFFER_FIELDS)
		return

	rows = _offer_rows(["sqi.name = %(name)s"], {"name": line.supplier_quotation_item})
	if not rows:
		frappe.throw(_("Row {0}: the supplier offer is not submitted any more").format(line.idx))
	row = rows[0]
	if row.item_code != line.item_code:
		frappe.throw(_("Row {0}: the supplier offer is for item {1}").format(line.idx, row.item_code))
	if row.company != request.company:
		frappe.throw(_("Row {0}: the supplier offer belongs to another company").format(line.idx))

	pricing = line.excess_pricing or EXCESS_TO_STOCK
	offer = _evaluate(row, line.stock_qty, on_date, settings, company_currency, pricing)
	suggested, minimum = sourcing_rates(
		offer["customer_unit_cost"], request.margin_percent, settings.minimum_margin_percent
	)
	line.update(
		{
			"supplier_quotation": row.supplier_quotation,
			"supplier": row.supplier,
			"supplier_rate": offer["unit_cost"],
			"lead_time_days": offer["lead_time_days"] or 0,
			"min_order_qty": offer["min_order_qty"],
			"valid_till": offer["valid_till"],
			"purchase_qty": offer["purchase_qty"],
			"excess_qty": offer["excess_qty"],
			"excess_pricing": pricing,
			"landed_cost": offer["landed_cost"],
			"pricing_cost": offer["customer_unit_cost"],
			"suggested_rate": suggested,
			"minimum_rate": minimum,
			"promised_date": offer["promised_date"],
		}
	)


def return_prices_to_quotation(request):
	"""On submit of a Sourcing Request: write price, promise and cost to the
	Quotation lines and tell the Quotation owner.

	Written straight to the database: purchasing cannot write Quotations, and
	the Quotation's modified time moves on, so a form open with old values must
	reload before it can save.
	"""
	quotation = _draft_quotation(request)
	if not quotation:
		return

	lines = {d.name: d for d in quotation.items}
	conversion_rate = flt(quotation.conversion_rate) or 1
	missing = []
	for item in request.items:
		line = lines.get(item.quotation_item)
		if not line:
			missing.append(str(item.idx))
			continue
		factor = flt(line.conversion_factor) or 1
		values = {
			"needs_sourcing": 1,
			"suggested_rate": flt(item.suggested_rate) * factor / conversion_rate,
			"minimum_rate": flt(item.minimum_rate) * factor / conversion_rate,
			"promised_date": item.promised_date,
			"quote_valid_till": item.valid_till,
			"sourced_stock_qty": flt(item.stock_qty),
			"sourced_qty_locked": int(item.excess_pricing == EXCESS_CUSTOMER_BEARS and flt(item.excess_qty) > 0),
			"estimated_landed_cost": flt(item.pricing_cost),
			"sourcing_request": request.name,
			"sourcing_request_item": item.name,
			"valuation_rate": flt(item.pricing_cost),
			"gross_profit": flt(
				line_gross_profit(line.base_rate, line.conversion_factor, flt(item.pricing_cost), line.stock_qty),
				quotation.precision("amount", line),
			),
		}
		line.update(values)
		frappe.db.set_value("Quotation Item", line.name, values, update_modified=False)

	quotation.db_set("sourcing_status", sourcing_status([d.as_dict() for d in quotation.items]))
	if missing:
		frappe.msgprint(
			_("Rows {0} are no longer on Quotation {1}; their prices were not returned.").format(
				", ".join(missing), quotation.name
			),
			indicator="orange",
		)
	_notify_owner(
		quotation,
		_("Prices for {0} item(s) of {1} are ready").format(len(request.items) - len(missing), quotation.name),
	)


def clear_prices_on_quotation(request):
	"""On cancel of a Sourcing Request: take its prices off the draft Quotation."""
	quotation = _draft_quotation(request, quiet=True)
	if not quotation:
		return
	changed = False
	for line in quotation.items:
		if line.get("sourcing_request") == request.name:
			values = dict(SOURCING_RESULT_FIELDS, **SOURCING_LINK_FIELDS)
			line.update(values)
			frappe.db.set_value("Quotation Item", line.name, values, update_modified=False)
			changed = True
	if changed:
		quotation.db_set("sourcing_status", sourcing_status([d.as_dict() for d in quotation.items]))


def check_quotation_before_cancel(request):
	"""A submitted Quotation priced from this request keeps it."""
	if not request.quotation:
		return
	quotation = frappe.db.get_value("Quotation", request.quotation, "docstatus")
	if quotation == 1 and frappe.db.exists(
		"Quotation Item", {"parent": request.quotation, "sourcing_request": request.name}
	):
		frappe.throw(
			_("Quotation {0} is submitted with these prices. It has to be cancelled first.").format(
				request.quotation
			)
		)


def _draft_quotation(request, quiet=False):
	if not request.quotation or not frappe.db.exists("Quotation", request.quotation):
		return None
	quotation = frappe.get_doc("Quotation", request.quotation)
	if quotation.docstatus != 0:
		if not quiet:
			frappe.msgprint(
				_("Quotation {0} is no longer a draft; the prices were not written to it.").format(quotation.name),
				indicator="orange",
			)
		return None
	return quotation


def _notify_owner(quotation, subject):
	email = frappe.db.get_value("User", quotation.owner, "email")
	if not email:
		return
	make_notification_logs(
		frappe._dict(
			{
				"type": "Alert",
				"document_type": "Quotation",
				"document_name": quotation.name,
				"subject": subject,
				"from_user": frappe.session.user,
			}
		),
		[email],
	)


# ---------------------------------------------------------------------------
# Supplier offers


@frappe.whitelist()
def get_supplier_offers(sourcing_request, excess_pricing=None):
	"""Ranked supplier offers for every line of a Sourcing Request.

	Offers are submitted Supplier Quotation Items made for the line (through an
	RFQ from this request or one it amends), plus other valid offers for the
	same item. excess_pricing: {line name: option} to evaluate with; else the
	line's own choice.
	"""
	doc = frappe.get_doc(SOURCING_REQUEST, sourcing_request)
	doc.check_permission("read")
	excess_pricing = frappe.parse_json(excess_pricing) or {}

	settings = get_company_settings(doc.company)
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	on_date = getdate(today())
	linked = _linked_offers(doc)

	result = []
	for line in doc.items:
		required = flt(line.qty) * (flt(line.conversion_factor) or 1)
		pricing = excess_pricing.get(line.name) or line.excess_pricing or EXCESS_TO_STOCK
		line_linked = {row.name: row for row in linked.get(line.quotation_item or line.name, [])}
		raw = {row.name: row for row in _other_offers(doc.company, line.item_code, on_date)}
		raw.update(line_linked)
		if line.supplier_quotation_item and line.supplier_quotation_item not in raw:
			for row in _offer_rows(["sqi.name = %(name)s"], {"name": line.supplier_quotation_item}):
				raw[row.name] = row

		offers = []
		for name, row in raw.items():
			offer = _evaluate(row, required, on_date, settings, company_currency, pricing, linked=name in line_linked)
			offer["suggested_rate"], offer["minimum_rate"] = sourcing_rates(
				offer["customer_unit_cost"], doc.margin_percent, settings.minimum_margin_percent
			)
			offers.append(offer)
		result.append(
			{
				"name": line.name,
				"idx": line.idx,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"qty": line.qty,
				"uom": line.uom,
				"stock_qty": required,
				"stock_uom": line.stock_uom,
				"excess_pricing": pricing,
				"selected": line.supplier_quotation_item,
				"offers": rank_offers(offers, doc.priority),
			}
		)

	return {
		"sourcing_request": doc.name,
		"company_currency": company_currency,
		"priority": doc.priority,
		"margin_percent": doc.margin_percent,
		"docstatus": doc.docstatus,
		"lines": result,
	}


@frappe.whitelist()
def select_offers(sourcing_request, selections):
	"""Set the chosen offer and excess pricing of draft Sourcing Request lines.

	selections: [{name, supplier_quotation_item, excess_pricing}]; an empty
	supplier_quotation_item clears the line. Saving re-reads and prices the offers.
	"""
	doc = frappe.get_doc(SOURCING_REQUEST, sourcing_request)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Sourcing Request {0} is not a draft").format(doc.name))

	lines = {d.name: d for d in doc.items}
	for selection in frappe.parse_json(selections) or []:
		selection = frappe._dict(selection)
		line = lines.get(selection.name)
		if not line:
			frappe.throw(_("Line {0} is not in Sourcing Request {1}").format(selection.name, doc.name))
		pricing = selection.excess_pricing or EXCESS_TO_STOCK
		if pricing not in EXCESS_PRICING_OPTIONS:
			frappe.throw(_("Row {0}: invalid excess pricing {1}").format(line.idx, pricing))
		line.supplier_quotation_item = selection.supplier_quotation_item or None
		line.excess_pricing = pricing

	doc.save()
	return {"status": doc.status}


def _linked_offers(request):
	"""{quotation_item (or line name): [offer rows]} made for the request's lines,
	through the Sourcing Request line their RFQ was made from. Matching on the
	quotation line keeps offers made for a cancelled request it amends."""
	keys = [d.quotation_item or d.name for d in request.items]
	rows = _offer_rows(
		["(sri.quotation_item in %(keys)s or sri.name in %(keys)s)"],
		{"keys": keys},
		join="inner join `tabSourcing Request Item` sri on sri.name = sqi.sourcing_request_item",
		extra_columns=", sri.quotation_item as sourcing_key, sri.name as sourcing_line",
	)
	result = {}
	for row in rows:
		result.setdefault(row.sourcing_key or row.sourcing_line, []).append(row)
	return result


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


def _offer_rows(conditions, values, limit=None, join="", extra_columns=""):
	return frappe.db.sql(
		f"""
		select
			sqi.name, sqi.parent as supplier_quotation, sqi.item_code, sqi.rate, sqi.base_rate,
			sqi.uom, sqi.conversion_factor, sqi.qty, sqi.lead_time_days,
			sqi.expected_delivery_date, ifnull(sqi.min_order_qty, 0) as min_order_qty,
			sqi.sourcing_request, sqi.sourcing_request_item,
			sq.supplier, sq.supplier_name, sq.currency, sq.transaction_date, sq.valid_till, sq.company,
			sup.landed_cost_percent{extra_columns}
		from `tabSupplier Quotation Item` sqi
		inner join `tabSupplier Quotation` sq on sq.name = sqi.parent
		left join `tabSupplier` sup on sup.name = sq.supplier
		{join}
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
# Sales Order -> Material Request -> Purchase Orders


@frappe.whitelist()
def request_purchase(sales_order):
	"""Draft Back-to-Back Purchase Material Request for the sourced lines of a
	submitted Sales Order: item, quantity, date, warehouse and the links to the
	Sales Order and Sourcing Request lines; no customer and no selling rate.

	Created as a system action and left in draft for the Material Request
	approval workflow. Lines already on an active Material Request or a
	Purchase Order are skipped.
	"""
	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("write")
	if so.docstatus != 1:
		frappe.throw(_("Submit Sales Order {0} first").format(so.name))
	if so.status in ("Closed", "On Hold", "Completed"):
		frappe.throw(_("Sales Order {0} is {1}").format(so.name, so.status))

	settings = get_company_settings(so.company)
	on_date = getdate(today())
	requested = _requested_sales_order_items(so.name)
	ordered = _ordered_sales_order_items(so.name)
	skipped = []

	request = frappe.new_doc("Material Request")
	request.update(
		{
			"material_request_type": "Purchase",
			"procurement_type": PROCUREMENT_TYPE,
			"company": so.company,
			"transaction_date": on_date,
		}
	)
	for line in so.items:
		if not line.get("needs_sourcing"):
			continue
		if not line.get("sourcing_request_item"):
			skipped.append(_("Row {0}: no price from purchasing").format(line.idx))
			continue
		if line.name in requested:
			skipped.append(_("Row {0}: already on Material Request {1}").format(line.idx, requested[line.name]))
			continue
		if line.name in ordered:
			skipped.append(_("Row {0}: already on Purchase Order {1}").format(line.idx, ordered[line.name]))
			continue

		warehouse = line.warehouse or settings.default_purchase_warehouse
		if not warehouse:
			frappe.throw(
				_(
					"Row {0}: set a warehouse on the line, or a Default Purchase Warehouse in Procurement Planning Settings"
				).format(line.idx)
			)
		request.append(
			"items",
			{
				"item_code": line.item_code,
				"item_name": line.item_name,
				"description": line.description or line.item_name,
				"qty": _stock_qty(line),
				"uom": line.stock_uom,
				"stock_uom": line.stock_uom,
				"conversion_factor": 1,
				"warehouse": warehouse,
				"schedule_date": _schedule_date(line, settings, on_date),
				"sales_order": so.name,
				"sales_order_item": line.name,
				"sourcing_request": line.sourcing_request,
				"sourcing_request_item": line.sourcing_request_item,
			},
		)

	if not request.get("items"):
		frappe.throw(_("Nothing to request:") + "<br>" + "<br>".join(skipped) if skipped else _("No sourced line"))

	request.schedule_date = min(d.schedule_date for d in request.items)
	request.flags.ignore_permissions = True
	request.insert()
	if not so.get("is_back_to_back"):
		so.db_set("is_back_to_back", 1)
	return {"material_request": request.name, "lines": len(request.items), "skipped": skipped}


@frappe.whitelist()
def make_back_to_back_purchase_orders(material_request):
	"""Draft Purchase Orders, one per supplier and currency, for a submitted
	Back-to-Back Material Request, at the offers chosen on its Sourcing Requests.

	The customer's quantity is linked to the Material Request and Sales Order
	lines; a supplier minimum above it goes on a separate unlinked line into
	stock. Lines fully ordered or already on a Purchase Order are skipped; an
	expired offer is used with a warning.
	"""
	mr = frappe.get_doc("Material Request", material_request)
	mr.check_permission("read")
	if not frappe.has_permission("Purchase Order", "create"):
		frappe.throw(_("Not permitted to create Purchase Orders"), frappe.PermissionError)
	if mr.docstatus != 1 or mr.get("procurement_type") != PROCUREMENT_TYPE:
		frappe.throw(_("Material Request {0} is not a submitted Back-to-Back request").format(mr.name))
	if mr.status in ("Stopped", "Closed"):
		frappe.throw(_("Material Request {0} is {1}").format(mr.name, mr.status))

	settings = get_company_settings(mr.company)
	on_date = getdate(today())
	on_order = _material_request_lines_on_order(mr.name)
	skipped, warnings, groups = [], [], {}

	for line in mr.items:
		remaining = flt(line.stock_qty) - flt(line.ordered_qty)
		if remaining <= 1e-9:
			continue
		if line.name in on_order:
			skipped.append(_("Row {0}: already on Purchase Order {1}").format(line.idx, on_order[line.name]))
			continue
		offer = _chosen_offer(line.get("sourcing_request_item"))
		if not offer:
			skipped.append(_("Row {0}: no submitted Sourcing Request with a supplier offer").format(line.idx))
			continue
		if offer.valid_till and getdate(offer.valid_till) < on_date:
			warnings.append(
				_("Row {0}: the offer of {1} expired on {2}; confirm the price with the supplier.").format(
					line.idx, offer.supplier, formatdate(offer.valid_till)
				)
			)
		groups.setdefault((offer.supplier, offer.currency), []).append((line, offer, remaining))

	created = [
		_make_purchase_order(mr, supplier, currency, entries, settings, on_date)
		for (supplier, currency), entries in groups.items()
	]
	return {"purchase_orders": created, "skipped": skipped, "warnings": warnings}


def _chosen_offer(sourcing_request_item):
	"""The Supplier Quotation Item chosen on a submitted Sourcing Request line."""
	if not sourcing_request_item:
		return None
	chosen = frappe.db.get_value(
		"Sourcing Request Item",
		{"name": sourcing_request_item, "docstatus": 1},
		["supplier_quotation_item", "min_order_qty"],
		as_dict=True,
	)
	if not chosen or not chosen.supplier_quotation_item:
		return None
	rows = _offer_rows(["sqi.name = %(name)s"], {"name": chosen.supplier_quotation_item})
	return rows[0] if rows else None


def _make_purchase_order(mr, supplier, currency, entries, settings, on_date):
	po = frappe.new_doc("Purchase Order")
	po.update(
		{
			"supplier": supplier,
			"company": mr.company,
			"transaction_date": on_date,
			"currency": currency,
			"ignore_pricing_rule": 1,
		}
	)

	for line, offer, customer_qty in entries:
		factor = flt(offer.conversion_factor) or 1
		_customer, excess_qty = purchase_order_split(customer_qty, flt(offer.min_order_qty) * factor)
		schedule_date = max(getdate(line.schedule_date), on_date) if line.schedule_date else on_date
		base = {
			"item_code": line.item_code,
			"schedule_date": schedule_date,
			"expected_delivery_date": _expected_delivery_date(offer, schedule_date, on_date),
			"supplier_quotation": offer.supplier_quotation,
		}

		customer_row = dict(base, **_offer_quantity(offer, customer_qty, line.stock_uom))
		customer_row.update(
			{
				"warehouse": line.warehouse,
				"material_request": mr.name,
				"material_request_item": line.name,
				"sales_order": line.sales_order,
				"sales_order_item": line.sales_order_item,
			}
		)
		po.append("items", customer_row)

		if excess_qty > 1e-9:
			excess_row = dict(base, **_offer_quantity(offer, excess_qty, line.stock_uom))
			excess_row["warehouse"] = settings.default_purchase_warehouse or line.warehouse
			po.append("items", excess_row)

	po.schedule_date = min(row.schedule_date for row in po.items)
	if po.meta.has_field("expected_delivery_date"):
		# not standard in v14; mandatory on the client's Purchase Order
		po.expected_delivery_date = max(row.expected_delivery_date for row in po.items)
	po.insert()
	return po.name


def _offer_quantity(offer, stock_qty, stock_uom):
	"""Quantity, UOM and rate of a PO line for stock_qty bought on an offer.

	In the offer's UOM when that gives a whole number, linked to the Supplier
	Quotation Item (ERPNext then requires the same UOM and conversion factor);
	otherwise in the stock UOM at the offer rate per stock unit, without that link.
	"""
	factor = flt(offer.conversion_factor) or 1
	qty = stock_qty / factor
	if factor == 1 or abs(qty - round(qty)) < 1e-9:
		return {
			"qty": round(qty) if factor != 1 else qty,
			"uom": offer.uom,
			"conversion_factor": factor,
			"rate": flt(offer.rate),
			"supplier_quotation_item": offer.name,
		}
	return {"qty": stock_qty, "uom": stock_uom, "conversion_factor": 1, "rate": flt(offer.rate) / factor}


def _requested_sales_order_items(sales_order):
	"""{sales_order_item: material_request} on Material Requests not cancelled."""
	rows = frappe.db.sql(
		"""
		select mri.sales_order_item, mri.parent
		from `tabMaterial Request Item` mri
		where mri.sales_order = %s and mri.docstatus < 2 and ifnull(mri.sales_order_item, '') != ''
		""",
		sales_order,
		as_dict=True,
	)
	return {row.sales_order_item: row.parent for row in rows}


def _material_request_lines_on_order(material_request):
	"""{material_request_item: purchase_order} for PO lines not cancelled."""
	rows = frappe.db.sql(
		"""
		select poi.material_request_item, poi.parent
		from `tabPurchase Order Item` poi
		where poi.material_request = %s and poi.docstatus < 2 and ifnull(poi.material_request_item, '') != ''
		""",
		material_request,
		as_dict=True,
	)
	return {row.material_request_item: row.parent for row in rows}


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
