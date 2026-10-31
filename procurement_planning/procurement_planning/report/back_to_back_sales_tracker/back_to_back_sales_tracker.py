# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Sales view of back-to-back Sales Order lines: stage, promised date, expected
arrival and days late. No supplier, Purchase Order or buying price."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from procurement_planning.planning import data_sources
from procurement_planning.planning.b2b_calculations import purchase_progress


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Not permitted to read Sales Orders"), frappe.PermissionError)
	return get_columns(), get_data(filters)


def get_data(filters):
	on_date = getdate(today())
	lines = data_sources.get_back_to_back_sales_order_lines(filters)
	purchases = data_sources.get_back_to_back_purchase_lines([line.name for line in lines])

	data = []
	for line in lines:
		promised = getdate(line.promised_date) if line.promised_date else None
		delivered_qty = flt(line.delivered_qty) * (flt(line.conversion_factor) or 1)
		progress = purchase_progress(
			purchases.get(line.name, []), flt(line.stock_qty), on_date, promised, delivered_qty
		)
		stage = progress["stage"]
		if filters.stage and stage != filters.stage:
			continue
		if not filters.stage and not filters.show_completed and stage == "Delivered":
			continue

		data.append(
			{
				"sales_order": line.sales_order,
				"stage": _(stage),
				"days_late": progress["days_late"],
				"expected_arrival": progress["expected_arrival"],
				"promised_date": promised,
				"required_by_date": line.order_required_by_date or line.delivery_date,
				"customer": line.customer,
				"priority": line.priority,
				"item_code": line.item_code,
				"qty": flt(line.stock_qty),
				"stock_uom": line.stock_uom,
				"received_qty": progress["received_qty"],
				"delivered_qty": delivered_qty,
				"item_name": line.item_name,
				"customer_name": line.customer_name,
			}
		)
	return data


def get_columns():
	return [
		{"fieldname": "sales_order", "label": _("Sales Order"), "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 110},
		{"fieldname": "days_late", "label": _("Days Late"), "fieldtype": "Int", "width": 90},
		{"fieldname": "expected_arrival", "label": _("Expected Arrival"), "fieldtype": "Date", "width": 110},
		{"fieldname": "promised_date", "label": _("Promised"), "fieldtype": "Date", "width": 100},
		{"fieldname": "required_by_date", "label": _("Required By"), "fieldtype": "Date", "width": 100},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 120},
		{"fieldname": "priority", "label": _("Priority"), "fieldtype": "Data", "width": 80},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 80},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "received_qty", "label": _("Received"), "fieldtype": "Float", "width": 80},
		{"fieldname": "delivered_qty", "label": _("Delivered"), "fieldtype": "Float", "width": 80},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 160},
	]
