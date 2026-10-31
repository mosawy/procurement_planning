# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Purchasing view of back-to-back Material Request lines: Sourcing Request,
supplier, Purchase Orders, stage, expected arrival and days late against the
required date. No customer or selling price."""

import frappe
from frappe import _
from frappe.utils import flt, getdate, today

from procurement_planning.planning import data_sources
from procurement_planning.planning.b2b_calculations import purchase_progress


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))
	if not frappe.has_permission("Material Request", "read"):
		frappe.throw(_("Not permitted to read Material Requests"), frappe.PermissionError)
	return get_columns(), get_data(filters)


def get_data(filters):
	on_date = getdate(today())
	lines = data_sources.get_back_to_back_request_lines(filters)
	purchases = data_sources.get_back_to_back_purchase_lines(
		[line.name for line in lines], key_field="material_request_item"
	)

	data = []
	for line in lines:
		po_lines = purchases.get(line.name, [])
		if filters.supplier and filters.supplier not in {po.supplier for po in po_lines}:
			continue
		required_by = getdate(line.schedule_date) if line.schedule_date else None
		progress = purchase_progress(po_lines, flt(line.stock_qty), on_date, required_by)
		stage = "MR Draft" if line.mr_docstatus == 0 else progress["stage"]
		if filters.stage and stage != filters.stage:
			continue
		if not filters.stage and not filters.show_completed and stage == "Received":
			continue

		data.append(
			{
				"material_request": line.material_request,
				"stage": _(stage),
				"days_late": progress["days_late"],
				"expected_arrival": progress["expected_arrival"],
				"required_by_date": required_by,
				"purchase_orders": ", ".join(sorted({po.purchase_order for po in po_lines})),
				"suppliers": ", ".join(sorted({po.supplier for po in po_lines})),
				"sourcing_request": line.sourcing_request,
				"priority": line.priority,
				"item_code": line.item_code,
				"qty": flt(line.stock_qty),
				"stock_uom": line.stock_uom,
				"ordered_qty": progress["ordered_qty"],
				"shipped_qty": progress["shipped_qty"],
				"received_qty": progress["received_qty"],
				"item_name": line.item_name,
			}
		)
	return data


def get_columns():
	return [
		{"fieldname": "material_request", "label": _("Material Request"), "fieldtype": "Link", "options": "Material Request", "width": 150},
		{"fieldname": "stage", "label": _("Stage"), "fieldtype": "Data", "width": 110},
		{"fieldname": "days_late", "label": _("Days Late"), "fieldtype": "Int", "width": 90},
		{"fieldname": "expected_arrival", "label": _("Expected Arrival"), "fieldtype": "Date", "width": 110},
		{"fieldname": "required_by_date", "label": _("Required By"), "fieldtype": "Date", "width": 100},
		{"fieldname": "purchase_orders", "label": _("Purchase Orders"), "fieldtype": "Data", "width": 160},
		{"fieldname": "suppliers", "label": _("Supplier"), "fieldtype": "Data", "width": 150},
		{"fieldname": "sourcing_request", "label": _("Sourcing Request"), "fieldtype": "Link", "options": "Sourcing Request", "width": 140},
		{"fieldname": "priority", "label": _("Priority"), "fieldtype": "Data", "width": 80},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 150},
		{"fieldname": "qty", "label": _("Qty"), "fieldtype": "Float", "width": 80},
		{"fieldname": "stock_uom", "label": _("UOM"), "fieldtype": "Link", "options": "UOM", "width": 70},
		{"fieldname": "ordered_qty", "label": _("Ordered"), "fieldtype": "Float", "width": 80},
		{"fieldname": "shipped_qty", "label": _("Shipped"), "fieldtype": "Float", "width": 80},
		{"fieldname": "received_qty", "label": _("Received"), "fieldtype": "Float", "width": 80},
		{"fieldname": "item_name", "label": _("Item Name"), "fieldtype": "Data", "width": 160},
	]
