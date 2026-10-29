# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Back-to-back purchasing: sourcing a Quotation and buying for a Sales Order.

Flow: draft Quotation (lines marked needs_sourcing) -> request_sourcing makes a
draft Back-to-Back Purchase Material Request -> standard RFQ and Supplier
Quotations (both carry material_request_item) -> get_supplier_offers /
select_offers write the chosen offer, cost and promise into the Quotation lines
-> standard Quotation -> Sales Order mapping copies them ->
make_back_to_back_purchase_orders raises draft Purchase Orders per supplier.

These endpoints use normal document permissions, since sales and purchasing
users run them.
"""

import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, formatdate, getdate, today

from procurement_planning.planning.b2b_calculations import (
	EXCESS_CUSTOMER_BEARS,
	EXCESS_TO_STOCK,
	evaluate_offer,
	purchase_order_split,
	quotation_rate,
	rank_offers,
	sourcing_status,
)
from procurement_planning.planning.settings import get_company_settings

PROCUREMENT_TYPE = "Back-to-Back"
OTHER_OFFERS_LIMIT = 20
EXCESS_PRICING_OPTIONS = (EXCESS_CUSTOMER_BEARS, EXCESS_TO_STOCK)


# ---------------------------------------------------------------------------
# Quotation -> sourcing request


@frappe.whitelist()
def request_sourcing(quotation, items=None):
	"""Create a draft Back-to-Back Purchase Material Request for Quotation lines.

	items: Quotation Item names; empty means every line marked needs_sourcing.
	Lines already on a Material Request that is not cancelled are skipped.
	"""
	doc = _get_draft_quotation(quotation)
	if not frappe.has_permission("Material Request", "create"):
		frappe.throw(_("Not permitted to create Material Requests"), frappe.PermissionError)

	selected = set(frappe.parse_json(items) or [])
	lines = [d for d in doc.items if (d.name in selected if selected else d.needs_sourcing)]
	if not lines:
		frappe.throw(_("Select the items to source, or tick Needs Sourcing on them"))

	requested = _requested_quotation_items(doc.name)
	new_lines = [d for d in lines if d.name not in requested]
	if not new_lines:
		frappe.throw(_("The selected items already have a sourcing request"))

	settings = get_company_settings(doc.company)
	transaction_date = getdate(today())
	schedule_date = getdate(doc.required_by_date) if doc.get("required_by_date") else add_days(transaction_date, 1)
	schedule_date = max(schedule_date, transaction_date)

	request = frappe.new_doc("Material Request")
	request.update(
		{
			"material_request_type": "Purchase",
			"company": doc.company,
			"transaction_date": transaction_date,
			"schedule_date": schedule_date,
			"procurement_type": PROCUREMENT_TYPE,
		}
	)

	for line in new_lines:
		warehouse = line.warehouse or settings.default_purchase_warehouse
		if not warehouse:
			frappe.throw(
				_(
					"Row {0}: set a warehouse on the line, or a Default Purchase Warehouse in Procurement Planning Settings"
				).format(line.idx)
			)
		stock_qty = flt(line.stock_qty) or flt(line.qty) * flt(line.conversion_factor or 1)
		request.append(
			"items",
			{
				"item_code": line.item_code,
				"item_name": line.item_name,
				"description": line.description or line.item_name,
				"qty": stock_qty,
				"uom": line.stock_uom,
				"stock_uom": line.stock_uom,
				"conversion_factor": 1,
				"warehouse": warehouse,
				"schedule_date": schedule_date,
				"sales_quotation": doc.name,
				"quotation_item": line.name,
			},
		)

	request.insert()

	for line in lines:
		line.needs_sourcing = 1
	doc.sourcing_request = request.name
	doc.sourcing_status = sourcing_status([d.as_dict() for d in doc.items])
	doc.save()

	return request.name


def _requested_quotation_items(quotation):
	return set(
		frappe.get_all(
			"Material Request Item",
			filters={"sales_quotation": quotation, "docstatus": ["<", 2]},
			pluck="quotation_item",
		)
	)


# ---------------------------------------------------------------------------
# Supplier offers


@frappe.whitelist()
def get_supplier_offers(quotation, excess_pricing=None):
	"""Ranked supplier offers for every sourcing line of a Quotation.

	Offers are submitted Supplier Quotation Items linked to the line through its
	sourcing Material Request, plus other valid offers for the same item.
	excess_pricing: {quotation_item: option} to evaluate with; a line's saved
	choice, else Excess to Stock, otherwise.
	"""
	doc = frappe.get_doc("Quotation", quotation)
	doc.check_permission("read")
	excess_pricing = frappe.parse_json(excess_pricing) or {}

	settings = get_company_settings(doc.company)
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	on_date = getdate(today())
	lines = [d for d in doc.items if d.needs_sourcing]
	linked = _linked_offers(doc.name)

	result = []
	for line in lines:
		required = flt(line.stock_qty) or flt(line.qty) * flt(line.conversion_factor or 1)
		pricing = excess_pricing.get(line.name) or line.get("excess_pricing") or EXCESS_TO_STOCK
		line_linked = {row.name: row for row in linked.get(line.name, [])}
		raw = {row.name: row for row in _other_offers(doc.company, line.item_code, on_date)}
		raw.update(line_linked)
		if line.get("supplier_quotation_item") and line.supplier_quotation_item not in raw:
			for row in _offer_rows(["sqi.name = %(name)s"], {"name": line.supplier_quotation_item}):
				raw[row.name] = row

		offers = [
			_evaluate(row, required, on_date, settings, company_currency, pricing, linked=name in line_linked)
			for name, row in raw.items()
		]
		offers = rank_offers(offers, doc.get("priority"))
		result.append(
			{
				"quotation_item": line.name,
				"idx": line.idx,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"qty": line.qty,
				"uom": line.uom,
				"stock_qty": required,
				"stock_uom": line.stock_uom,
				"rate": line.rate,
				"excess_pricing": pricing,
				"selected": line.get("supplier_quotation_item"),
				"offers": offers,
			}
		)

	return {
		"quotation": doc.name,
		"currency": doc.currency,
		"company_currency": company_currency,
		"conversion_rate": doc.conversion_rate,
		"priority": doc.get("priority"),
		"default_margin_percent": settings.default_margin_percent,
		"docstatus": doc.docstatus,
		"lines": result,
	}


def _linked_offers(quotation):
	"""{quotation_item: [offer rows]} through the sourcing Material Request lines."""
	rows = _offer_rows(
		["mri.sales_quotation = %(quotation)s"],
		{"quotation": quotation},
		join_mr=True,
	)
	result = {}
	for row in rows:
		result.setdefault(row.quotation_item, []).append(row)
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


def _offer_rows(conditions, values, join_mr=False, limit=None):
	join = (
		"inner join `tabMaterial Request Item` mri on mri.name = sqi.material_request_item"
		if join_mr
		else ""
	)
	select_mr = ", mri.quotation_item" if join_mr else ""
	return frappe.db.sql(
		f"""
		select
			sqi.name, sqi.parent as supplier_quotation, sqi.item_code, sqi.rate, sqi.base_rate,
			sqi.uom, sqi.conversion_factor, sqi.qty, sqi.lead_time_days,
			sqi.expected_delivery_date, ifnull(sqi.min_order_qty, 0) as min_order_qty,
			sqi.material_request, sqi.material_request_item,
			sq.supplier, sq.supplier_name, sq.currency, sq.transaction_date, sq.valid_till,
			sup.landed_cost_percent{select_mr}
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


@frappe.whitelist()
def select_offers(quotation, selections):
	"""Write chosen offers into draft Quotation lines.

	selections: [{quotation_item, supplier_quotation_item, excess_pricing,
	margin_percent, set_rate}]. With set_rate the line rate is set from the
	customer unit cost and the margin. Offers are re-read and re-evaluated here.
	"""
	doc = _get_draft_quotation(quotation)
	selections = frappe.parse_json(selections) or []
	settings = get_company_settings(doc.company)
	company_currency = frappe.get_cached_value("Company", doc.company, "default_currency")
	on_date = getdate(today())
	lines = {d.name: d for d in doc.items}

	for selection in selections:
		selection = frappe._dict(selection)
		line = lines.get(selection.quotation_item)
		if not line:
			frappe.throw(_("Quotation Item {0} is not in Quotation {1}").format(selection.quotation_item, doc.name))

		if not selection.supplier_quotation_item:
			_clear_offer(line)
			continue

		rows = _offer_rows(["sqi.name = %(name)s"], {"name": selection.supplier_quotation_item})
		if not rows:
			frappe.throw(_("Row {0}: supplier offer not found or not submitted").format(line.idx))
		row = rows[0]
		if row.item_code != line.item_code:
			frappe.throw(_("Row {0}: the supplier offer is for item {1}").format(line.idx, row.item_code))
		if frappe.db.get_value("Supplier Quotation", row.supplier_quotation, "company") != doc.company:
			frappe.throw(_("Row {0}: the supplier offer belongs to another company").format(line.idx))

		pricing = selection.excess_pricing or EXCESS_TO_STOCK
		if pricing not in EXCESS_PRICING_OPTIONS:
			frappe.throw(_("Row {0}: invalid excess pricing {1}").format(line.idx, pricing))

		required = flt(line.stock_qty) or flt(line.qty) * flt(line.conversion_factor or 1)
		offer = _evaluate(row, required, on_date, settings, company_currency, pricing)
		line.needs_sourcing = 1
		line.supplier_quotation = offer["supplier_quotation"]
		line.supplier_quotation_item = offer["supplier_quotation_item"]
		line.sourcing_supplier = offer["supplier"]
		line.estimated_landed_cost = offer["landed_cost"]
		line.promised_date = offer["promised_date"]
		line.purchase_qty = offer["purchase_qty"]
		line.excess_qty = offer["excess_qty"]
		line.excess_pricing = pricing if offer["excess_qty"] else None
		line.quote_valid_till = offer["valid_till"]

		if cint(selection.set_rate):
			margin = settings.default_margin_percent if selection.margin_percent in (None, "") else flt(selection.margin_percent)
			if margin >= 100:
				frappe.throw(_("Row {0}: margin must be below 100%").format(line.idx))
			line.margin_type = ""
			line.margin_rate_or_amount = 0
			line.discount_percentage = 0
			line.discount_amount = 0
			line.rate = quotation_rate(
				offer["customer_unit_cost"], margin, flt(line.conversion_factor) or 1, flt(doc.conversion_rate) or 1
			)

	doc.sourcing_status = sourcing_status([d.as_dict() for d in doc.items])
	doc.save()
	return {"sourcing_status": doc.sourcing_status}


def _clear_offer(line):
	for fieldname in (
		"supplier_quotation",
		"supplier_quotation_item",
		"sourcing_supplier",
		"promised_date",
		"excess_pricing",
		"quote_valid_till",
	):
		line.set(fieldname, None)
	for fieldname in ("estimated_landed_cost", "purchase_qty", "excess_qty"):
		line.set(fieldname, 0)


def _get_draft_quotation(quotation):
	doc = frappe.get_doc("Quotation", quotation)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Quotation {0} is not a draft").format(doc.name))
	return doc


# ---------------------------------------------------------------------------
# Quotation hooks


def validate_quotation(doc, method=None):
	"""Keep the sourcing status in line with the lines."""
	if doc.meta.has_field("sourcing_status"):
		doc.sourcing_status = sourcing_status([d.as_dict() for d in doc.items])


def before_submit_quotation(doc, method=None):
	"""Block submit while a sourcing line has no supplier offer; warn when the
	quotation is valid longer than a supplier offer it relies on."""
	missing = [str(d.idx) for d in doc.items if d.get("needs_sourcing") and not d.get("supplier_quotation_item")]
	if missing:
		frappe.throw(
			_("Rows {0} need sourcing and have no supplier offer selected. Use Supplier Offers first.").format(
				", ".join(missing)
			)
		)

	if not doc.valid_till:
		return
	valid_till = getdate(doc.valid_till)
	shorter = [
		_("Row {0}: offer valid till {1}").format(d.idx, formatdate(d.quote_valid_till))
		for d in doc.items
		if d.get("needs_sourcing") and d.get("quote_valid_till") and getdate(d.quote_valid_till) < valid_till
	]
	if shorter:
		frappe.msgprint(
			_("This quotation is valid until {0}, longer than these supplier offers:").format(
				formatdate(doc.valid_till)
			)
			+ "<br>"
			+ "<br>".join(shorter),
			title=_("Supplier offer validity"),
			indicator="orange",
		)


# ---------------------------------------------------------------------------
# Sales Order -> Purchase Orders


@frappe.whitelist()
def make_back_to_back_purchase_orders(sales_order):
	"""Draft Purchase Orders, one per supplier and currency, for the sourcing
	lines of a submitted Sales Order.

	The customer's quantity is linked to the Sales Order line; a supplier
	minimum order above it goes on a separate unlinked line into stock. Lines
	that already have a Purchase Order line (not cancelled) are skipped.
	"""
	so = frappe.get_doc("Sales Order", sales_order)
	so.check_permission("read")
	if so.docstatus != 1:
		frappe.throw(_("Submit Sales Order {0} first").format(so.name))
	if so.status in ("Closed", "On Hold", "Completed"):
		frappe.throw(_("Sales Order {0} is {1}").format(so.name, so.status))
	if not frappe.has_permission("Purchase Order", "create"):
		frappe.throw(_("Not permitted to create Purchase Orders"), frappe.PermissionError)

	settings = get_company_settings(so.company)
	on_date = getdate(today())
	ordered = _ordered_sales_order_items(so.name)
	skipped = []
	groups = {}

	for line in so.items:
		if not line.get("needs_sourcing"):
			continue
		if line.name in ordered:
			skipped.append(_("Row {0}: already on Purchase Order {1}").format(line.idx, ordered[line.name]))
			continue
		if not line.get("supplier_quotation_item"):
			skipped.append(_("Row {0}: no supplier offer selected").format(line.idx))
			continue

		rows = _offer_rows(["sqi.name = %(name)s"], {"name": line.supplier_quotation_item})
		if not rows:
			skipped.append(_("Row {0}: supplier offer {1} is not submitted").format(line.idx, line.supplier_quotation))
			continue
		offer = rows[0]
		groups.setdefault((offer.supplier, offer.currency), []).append((line, offer))

	created = []
	for (supplier, currency), entries in groups.items():
		created.append(_make_purchase_order(so, supplier, currency, entries, settings, on_date))

	if created and not so.get("is_back_to_back"):
		so.db_set("is_back_to_back", 1)

	return {"purchase_orders": created, "skipped": skipped}


def _make_purchase_order(so, supplier, currency, entries, settings, on_date):
	po = frappe.new_doc("Purchase Order")
	po.update(
		{
			"supplier": supplier,
			"company": so.company,
			"transaction_date": on_date,
			"currency": currency,
			"ignore_pricing_rule": 1,
		}
	)
	mr_remaining = _material_request_remaining([offer.material_request_item for _l, offer in entries])

	for line, offer in entries:
		factor = flt(offer.conversion_factor) or 1
		customer_stock_qty = flt(line.stock_qty) or flt(line.qty) * flt(line.conversion_factor or 1)
		customer_qty, excess_qty = purchase_order_split(customer_stock_qty, flt(offer.min_order_qty) * factor)
		schedule_date = _schedule_date(line, settings, on_date)
		base = {
			"item_code": line.item_code,
			"uom": offer.uom,
			"conversion_factor": factor,
			"rate": flt(offer.rate),
			"schedule_date": schedule_date,
			"supplier_quotation": offer.supplier_quotation,
			"supplier_quotation_item": offer.name,
		}

		customer_row = dict(base)
		customer_row.update(
			{
				"qty": customer_qty / factor,
				"warehouse": line.warehouse or settings.default_purchase_warehouse,
				"sales_order": so.name,
				"sales_order_item": line.name,
			}
		)
		remaining = mr_remaining.get(offer.material_request_item)
		if remaining is not None and customer_qty <= remaining + 1e-9:
			customer_row["material_request"] = offer.material_request
			customer_row["material_request_item"] = offer.material_request_item
		po.append("items", customer_row)

		if excess_qty > 1e-9:
			excess_row = dict(base)
			excess_row.update(
				{
					"qty": excess_qty / factor,
					"warehouse": settings.default_purchase_warehouse or line.warehouse,
				}
			)
			po.append("items", excess_row)

	po.schedule_date = min(row.schedule_date for row in po.items)
	po.insert()
	return po.name


def _schedule_date(line, settings, on_date):
	"""Expected receipt: the promise less the delivery buffer, else the delivery date."""
	if line.get("promised_date"):
		date = add_days(getdate(line.promised_date), -cint(settings.delivery_buffer_days))
	elif line.get("delivery_date"):
		date = getdate(line.delivery_date)
	else:
		date = on_date
	return max(getdate(date), on_date)


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

