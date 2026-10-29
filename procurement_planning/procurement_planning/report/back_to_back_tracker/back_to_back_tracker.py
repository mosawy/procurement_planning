# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Where each back-to-back Sales Order line stands: ordered, shipped, received,
delivered, expected arrival and days late against the date promised to the
customer."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from procurement_planning.planning import data_sources
from procurement_planning.planning.b2b_calculations import back_to_back_stage, days_late

DONE_STAGES = ("Received", "Delivered")


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
		po_lines = purchases.get(line.name, [])
		submitted = [po for po in po_lines if po.docstatus == 1]
		required_qty = flt(line.stock_qty)
		ordered_qty = sum(flt(po.stock_qty) for po in submitted)
		received_qty = sum(flt(po.received_qty) for po in submitted)
		shipped_qty = max(sum(flt(po.shipped_qty) for po in submitted), received_qty)
		delivered_qty = flt(line.delivered_qty) * (flt(line.conversion_factor) or 1)
		stage = back_to_back_stage(
			ordered_qty,
			shipped_qty,
			received_qty,
			delivered_qty,
			required_qty,
			has_draft_po=any(po.docstatus == 0 for po in po_lines),
		)
		if filters.stage and stage != filters.stage:
			continue
		if not filters.stage and not filters.show_completed and stage == "Delivered":
			continue

		expected = _expected_arrival(submitted)
		promised = getdate(line.promised_date) if line.promised_date else None
		late = None
		if stage not in DONE_STAGES:
			late = days_late(max(expected or on_date, on_date), promised)

		data.append(
			{
				"sales_order": line.sales_order,
				"customer": line.customer,
				"customer_name": line.customer_name,
				"priority": line.priority,
				"item_code": line.item_code,
				"item_name": line.item_name,
				"stock_uom": line.stock_uom,
				"qty": required_qty,
				"required_by_date": line.order_required_by_date or line.delivery_date,
				"promised_date": promised,
				"suppliers": ", ".join(sorted({po.supplier for po in po_lines})) or line.sourcing_supplier,
				"purchase_orders": ", ".join(sorted({po.purchase_order for po in po_lines})),
				"ordered_qty": ordered_qty,
				"shipped_qty": shipped_qty,
				"received_qty": received_qty,
				"delivered_qty": delivered_qty,
				"stage": _(stage),
				"expected_arrival": expected,
				"days_late": late,
			}
		)

	return data


def _expected_arrival(po_lines):
	"""Latest expected arrival of the open part of the lines: shipment arrival date
	for shipped quantity, else the PO date."""
	dates = []
	for po in po_lines:
		if flt(po.received_qty) >= flt(po.stock_qty):
			continue
		if po.arrival_date and flt(po.shipped_qty) > flt(po.received_qty):
			dates.append(getdate(po.arrival_date))
		if flt(po.shipped_qty) < flt(po.stock_qty) and po.expected_date:
			dates.append(getdate(po.expected_date))
	return max(dates) if dates else None


def get_columns():
	return [
		{"fieldname": "sales_order", "label": _("Sales Order"), "fieldtype": "Link", "options": "Sales Order", "width": 150},
		{"fieldname": "customer", "label": _("Customer"), "fieldtype": "Link", "options": "Customer", "width": 120},
		{"fieldname": "customer_name", "label": _("Customer Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "priority", "label": _("Priority"), "fieldtype": "Data", "width": 80},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 160},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 80},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "required_by_date", "label": _("Required By"), "fieldtype": "Date", "width": 100},
		{"fieldname": "promised_date", "label": _("Promised"), "fieldtype": "Date", "width": 100},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 110},
		{"fieldname": "expected_arrival", "label": _("Expected Arrival"), "fieldtype": "Date", "width": 110},
		{"fieldname": "days_late", "label": _("Days Late"), "fieldtype": "Int", "width": 90},
		{"fieldname": "suppliers", "label": _("Supplier"), "fieldtype": "Data", "width": 150},
		{"fieldname": "purchase_orders", "label": _("Purchase Orders"), "fieldtype": "Data", "width": 160},
		{"fieldname": "ordered_qty", "label": _("Ordered"), "fieldtype": "Float", "width": 80},
		{"fieldname": "shipped_qty", "label": _("Shipped"), "fieldtype": "Float", "width": 80},
		{"fieldname": "received_qty", "label": _("Received"), "fieldtype": "Float", "width": 80},
		{"fieldname": "delivered_qty", "label": _("Delivered"), "fieldtype": "Float", "width": 80},
	]
