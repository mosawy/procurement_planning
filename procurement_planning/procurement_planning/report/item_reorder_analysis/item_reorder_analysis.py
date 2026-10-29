# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import flt, formatdate

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning import data_sources

QUANTITY_FIELDS = (
	"current_stock",
	"reservation_stock",
	"transit_stock",
	"net_sales_qty",
	"open_so_qty",
	"open_po_qty",
	"pending_pr_qty",
)


def execute(filters=None):
	# Development-phase access, also declared in the report JSON roles.
	# Prepared Report and Custom Role paths are guarded in procurement_planning.permissions.
	frappe.only_for(ALLOWED_ROLES)

	filters = frappe._dict(filters or {})
	params = data_sources.build_query_params(filters.company, filters.item_group, filters.analysis_months)
	return get_columns(), get_data(params), get_message(params)


def get_data(params):
	items = data_sources.get_items(params)
	sources = (
		data_sources.get_stock_balances(params),
		data_sources.get_net_sales(params),
		data_sources.get_open_sales_orders(params),
		data_sources.get_open_purchase_orders(params),
		data_sources.get_pending_purchase_requests(params),
	)

	data = []
	for item_code, item in items.items():
		row = frappe._dict(
			item_code=item_code,
			item_name=item.item_name,
			sap_code=item.sap_code,
			company=params.company,
			stock_uom=item.stock_uom,
			lead_time_days=item.lead_time_days,
			min_order_qty=item.min_order_qty,
			safety_stock=item.safety_stock,
			next_expected_date=None,
		)
		for source in sources:
			row.update(source.get(item_code) or {})

		for fieldname in QUANTITY_FIELDS:
			row[fieldname] = flt(row.get(fieldname))

		data.append(row)

	return data


def get_message(params):
	return _(
		"Net Sales Qty is stock-movement based: quantity delivered through Delivery Notes and "
		"stock-updating Sales Invoices, net of returns, from {0} to {1}. It is not accounting net sales."
	).format(formatdate(params.from_date), formatdate(params.to_date))


def get_columns():
	return [
		{"label": _("Item Code"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Item Name"), "fieldname": "item_name", "fieldtype": "Data", "width": 200},
		{"label": _("SAP Code"), "fieldname": "sap_code", "fieldtype": "Data", "width": 110},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Stock UOM"), "fieldname": "stock_uom", "fieldtype": "Link", "options": "UOM", "width": 90},
		{"label": _("Current Stock"), "fieldname": "current_stock", "fieldtype": "Float", "width": 110},
		{"label": _("Reservation Stock"), "fieldname": "reservation_stock", "fieldtype": "Float", "width": 120},
		{"label": _("Transit Stock"), "fieldname": "transit_stock", "fieldtype": "Float", "width": 110},
		{
			"label": _("Net Sales Qty (Stock Movement)"),
			"fieldname": "net_sales_qty",
			"fieldtype": "Float",
			"width": 140,
		},
		{"label": _("Open SO Qty"), "fieldname": "open_so_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Open PO Qty"), "fieldname": "open_po_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Pending PR Qty"), "fieldname": "pending_pr_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Next Expected PO Date"), "fieldname": "next_expected_date", "fieldtype": "Date", "width": 130},
		{"label": _("Item Lead Time Days"), "fieldname": "lead_time_days", "fieldtype": "Int", "width": 110},
		{"label": _("Minimum Order Qty"), "fieldname": "min_order_qty", "fieldtype": "Float", "width": 110},
		{"label": _("Item Safety Stock"), "fieldname": "safety_stock", "fieldtype": "Float", "width": 110},
	]
