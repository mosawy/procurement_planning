# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Plan vs actual for Purchasing Blanket Orders: planned, ordered, received, remaining.

The agreed rate is in the agreement's currency (the supplier's default currency;
v14 Blanket Orders have none of their own); values are in the company currency
at today's exchange rate."""

import frappe
from frappe import _
from frappe.utils import flt, today

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning.data_sources import get_exchange_rates


def execute(filters=None):
	frappe.only_for(ALLOWED_ROLES)
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))
	return get_columns(filters), get_data(filters)


def get_data(filters):
	conditions = ["bo.blanket_order_type = 'Purchasing'", "bo.company = %(company)s", "bo.docstatus < 2"]
	if filters.supplier:
		conditions.append("bo.supplier = %(supplier)s")
	if filters.blanket_order:
		conditions.append("bo.name = %(blanket_order)s")
	if filters.from_date:
		conditions.append("bo.to_date >= %(from_date)s")
	if filters.to_date:
		conditions.append("bo.from_date <= %(to_date)s")
	if not filters.include_drafts:
		conditions.append("bo.docstatus = 1")

	rows = frappe.db.sql(
		f"""
		select
			bo.name as blanket_order, bo.supplier, bo.from_date, bo.to_date, bo.docstatus,
			boi.item_code, i.item_name, boi.qty as planned_qty, ifnull(boi.ordered_qty, 0) as ordered_qty,
			boi.rate, sup.default_currency as supplier_currency,
			(
				select ifnull(sum(poi.received_qty * poi.conversion_factor), 0)
				from `tabPurchase Order Item` poi
				inner join `tabPurchase Order` po on po.name = poi.parent
				where po.docstatus = 1 and poi.blanket_order = bo.name and poi.item_code = boi.item_code
			) as received_qty
		from `tabBlanket Order` bo
		inner join `tabBlanket Order Item` boi on boi.parent = bo.name and boi.parenttype = 'Blanket Order'
		left join `tabItem` i on i.name = boi.item_code
		left join `tabSupplier` sup on sup.name = bo.supplier
		where {" and ".join(conditions)}
		order by bo.supplier, bo.from_date, boi.idx
		""",
		filters,
		as_dict=True,
	)

	company_currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	rates = get_exchange_rates(
		{row.supplier_currency or company_currency for row in rows}, company_currency, today()
	)
	for row in rows:
		row.currency = row.supplier_currency or company_currency
		row.company_currency = company_currency
		row.exchange_rate = rates.get(row.currency) or 0
		row.status = _("Draft") if row.docstatus == 0 else _("Submitted")
		row.remaining_qty = flt(row.planned_qty) - flt(row.ordered_qty)
		row.used_percent = flt(row.ordered_qty) / flt(row.planned_qty) * 100 if flt(row.planned_qty) else 0
		# No exchange rate: values stay empty rather than mixing currencies.
		base_rate = flt(row.rate) * row.exchange_rate if row.exchange_rate else None
		row.planned_value = flt(row.planned_qty) * base_rate if base_rate is not None else None
		row.ordered_value = flt(row.ordered_qty) * base_rate if base_rate is not None else None
	return rows


def get_columns(filters):
	return [
		{"label": _("Blanket Order"), "fieldname": "blanket_order", "fieldtype": "Link", "options": "Blanket Order", "width": 150},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 90},
		{"label": _("Supplier"), "fieldname": "supplier", "fieldtype": "Link", "options": "Supplier", "width": 160},
		{"label": _("From"), "fieldname": "from_date", "fieldtype": "Date", "width": 95},
		{"label": _("To"), "fieldname": "to_date", "fieldtype": "Date", "width": 95},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("Planned Qty"), "fieldname": "planned_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Ordered Qty"), "fieldname": "ordered_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Received Qty"), "fieldname": "received_qty", "fieldtype": "Float", "width": 100},
		{"label": _("Remaining Qty"), "fieldname": "remaining_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Ordered %"), "fieldname": "used_percent", "fieldtype": "Percent", "width": 90},
		{"label": _("Agreed Rate"), "fieldname": "rate", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 80},
		{"label": _("Exchange Rate"), "fieldname": "exchange_rate", "fieldtype": "Float", "width": 100},
		{"label": _("Planned Value"), "fieldname": "planned_value", "fieldtype": "Currency", "options": "company_currency", "width": 130},
		{"label": _("Ordered Value"), "fieldname": "ordered_value", "fieldtype": "Currency", "options": "company_currency", "width": 130},
	]
