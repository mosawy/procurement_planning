# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Back-to-back cost per Sales Order line: its Purchase Order lines at actual
cost where received (Purchase Receipt valuation, which includes Landed Cost
Vouchers) and estimated cost otherwise, against the estimate the price was
built on, with the selling rate and margin. Ordered Qty counts submitted
Purchase Orders only; draft quantity has its own column."""

import frappe
from frappe import _
from frappe.utils import flt

from procurement_planning.planning import data_sources
from procurement_planning.planning.b2b_calculations import (
	estimated_landed_cost,
	margin_percent,
	purchase_line_cost,
	weighted_average_cost,
)
from procurement_planning.planning.settings import get_company_settings


def execute(filters=None):
	filters = frappe._dict(filters or {})
	if not filters.company:
		frappe.throw(_("Company is required"))
	if not frappe.has_permission("Sales Order", "read"):
		frappe.throw(_("Not permitted to read Sales Orders"), frappe.PermissionError)
	return get_columns(), get_data(filters)


def get_data(filters):
	settings = get_company_settings(filters.company)
	company_currency = frappe.get_cached_value("Company", filters.company, "default_currency")
	lines = data_sources.get_back_to_back_sales_order_lines(filters)
	purchases = data_sources.get_back_to_back_purchase_lines([line.name for line in lines])

	data = []
	for line in lines:
		po_lines = purchases.get(line.name, [])
		if filters.supplier and filters.supplier not in {po.supplier for po in po_lines}:
			continue

		children = []
		parts = []
		for po in po_lines:
			landed_percent = (
				flt(po.landed_cost_percent) if po.landed_cost_percent else settings.default_landed_cost_percent
			)
			estimate = estimated_landed_cost(
				flt(po.base_unit_rate),
				landed_percent,
				settings.fx_buffer_percent,
				po.currency != company_currency,
			)
			receipt_qty = flt(po.receipt_qty)
			qty = max(flt(po.stock_qty), receipt_qty)
			cost, basis = purchase_line_cost(receipt_qty, flt(po.receipt_value), qty - receipt_qty, estimate)
			if cost is not None:
				parts.append((qty, cost))
			children.append(
				{
					"id": po.name,
					"parent_id": line.name,
					"indent": 1,
					"reference_type": "Purchase Order",
					"reference": po.purchase_order,
					"item_code": po.item_code,
					"party": po.supplier_name or po.supplier,
					"status": _("Draft") if po.docstatus == 0 else _(po.status),
					"qty": qty,
					"ordered_qty": qty if po.docstatus == 1 else 0,
					"draft_qty": qty if po.docstatus == 0 else 0,
					"received_qty": receipt_qty,
					"estimated_cost": estimate,
					"unit_cost": cost,
					"cost_basis": _(basis),
				}
			)

		_qty, average = weighted_average_cost(parts)
		estimate = flt(line.estimated_landed_cost) or None
		selling = flt(line.base_net_rate) / (flt(line.conversion_factor) or 1)
		variance = average - estimate if average is not None and estimate else None
		data.append(
			{
				"id": line.name,
				"parent_id": None,
				"indent": 0,
				"reference_type": "Sales Order",
				"reference": line.sales_order,
				"item_code": line.item_code,
				"party": line.customer_name or line.customer,
				"status": _(line.sales_order_status),
				"qty": flt(line.stock_qty),
				"received_qty": sum(flt(child["received_qty"]) for child in children),
				"ordered_qty": sum(child["ordered_qty"] for child in children),
				"draft_qty": sum(child["draft_qty"] for child in children),
				"estimated_cost": estimate,
				"unit_cost": average,
				"cost_basis": _basis([child["cost_basis"] for child in children]),
				"variance": variance,
				"variance_percent": variance / estimate * 100 if variance is not None else None,
				"selling_rate": selling,
				"estimated_margin": margin_percent(selling, estimate) if estimate else None,
				"margin": margin_percent(selling, average) if average is not None else None,
			}
		)
		data.extend(children)

	return data


def _basis(values):
	values = set(values)
	if not values:
		return None
	if len(values) == 1:
		return values.pop()
	return _("Mixed")


def get_columns():
	return [
		{
			"fieldname": "reference",
			"label": _("Document"),
			"fieldtype": "Dynamic Link",
			"options": "reference_type",
			"width": 200,
		},
		{"fieldname": "item_code", "label": _("Item"), "fieldtype": "Link", "options": "Item", "width": 160},
		{"fieldname": "party", "label": _("Customer / Supplier"), "fieldtype": "Data", "width": 180},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 100},
		{"fieldname": "qty", "label": _("Qty (Stock UOM)"), "fieldtype": "Float", "width": 110},
		{"fieldname": "ordered_qty", "label": _("Ordered Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "draft_qty", "label": _("Draft PO Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "received_qty", "label": _("Received Qty"), "fieldtype": "Float", "width": 100},
		{"fieldname": "estimated_cost", "label": _("Estimated Unit Cost"), "fieldtype": "Currency", "width": 130},
		{"fieldname": "unit_cost", "label": _("Unit Cost"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "cost_basis", "label": _("Cost Basis"), "fieldtype": "Data", "width": 90},
		{"fieldname": "variance", "label": _("Variance"), "fieldtype": "Currency", "width": 110},
		{"fieldname": "variance_percent", "label": _("Variance %"), "fieldtype": "Percent", "width": 90},
		{"fieldname": "selling_rate", "label": _("Selling Rate"), "fieldtype": "Currency", "width": 120},
		{"fieldname": "estimated_margin", "label": _("Estimated Margin %"), "fieldtype": "Percent", "width": 120},
		{"fieldname": "margin", "label": _("Margin %"), "fieldtype": "Percent", "width": 100},
	]
