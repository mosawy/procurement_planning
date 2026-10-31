# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Custom fields and property setters this app adds to standard ERPNext DocTypes.

Created on install and refreshed on every migrate, so the definitions live in
code rather than in exported fixtures.
"""

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

VARIANCE_REASONS = "\n".join(
	[
		"",
		"Budget Constraint",
		"Supplier Availability",
		"Minimum Order Qty",
		"Order Multiple",
		"Supplier Commitment",
		"Opportunity Buy",
		"Planner Judgement",
		"Other",
	]
)

PRIORITIES = "\nUrgent\nNormal\nFlexible"


def order_fields(insert_after):
	"""Required-by date and priority, shared by Quotation and Sales Order so the
	standard Quotation -> Sales Order mapping copies them."""
	return [
		{
			"fieldname": "required_by_date",
			"label": "Required By Date",
			"fieldtype": "Date",
			"insert_after": insert_after,
			"description": "Date the customer needs the goods.",
		},
		{
			"fieldname": "priority",
			"label": "Priority",
			"fieldtype": "Select",
			"options": PRIORITIES,
			"insert_after": "required_by_date",
			"in_standard_filter": 1,
			"description": "Urgent ranks supplier offers by earliest promise, others by cost.",
		},
	]


def sourcing_item_fields():
	"""Back-to-back fields on Quotation Item and Sales Order Item (same names, so
	the standard Quotation -> Sales Order mapping copies them).

	Sales sees only what it prices with: suggested and minimum rate, promised
	date and offer validity. Supplier and offer stay on the Sourcing Request; the
	cost the price is built on is on permlevel 1.
	"""
	return [
		{
			"fieldname": "needs_sourcing",
			"label": "Needs Sourcing",
			"fieldtype": "Check",
			"insert_after": "item_name",
			"description": "Bought back-to-back for this order: purchasing finds a supplier offer and returns a price.",
		},
		{
			"fieldname": "sourcing_section",
			"label": "Back-to-Back Sourcing",
			"fieldtype": "Section Break",
			"insert_after": "gross_profit",
			"collapsible": 1,
			"depends_on": "eval:doc.needs_sourcing",
		},
		{
			"fieldname": "suggested_rate",
			"label": "Suggested Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "sourcing_section",
			"read_only": 1,
			"description": "Rate for the target margin, per this line's UOM.",
		},
		{
			"fieldname": "minimum_rate",
			"label": "Minimum Rate",
			"fieldtype": "Currency",
			"options": "currency",
			"insert_after": "suggested_rate",
			"read_only": 1,
			"description": "Lowest rate that can be submitted without the exception role.",
		},
		{
			"fieldname": "promised_date",
			"label": "Promised Date",
			"fieldtype": "Date",
			"insert_after": "minimum_rate",
			"read_only": 1,
			"description": "Date that can be promised to the customer.",
		},
		{
			"fieldname": "quote_valid_till",
			"label": "Price Valid Till",
			"fieldtype": "Date",
			"insert_after": "promised_date",
			"read_only": 1,
			"description": "The suggested and minimum rates hold until this date.",
		},
		{
			"fieldname": "sourcing_column",
			"fieldtype": "Column Break",
			"insert_after": "quote_valid_till",
		},
		{
			"fieldname": "sourced_stock_qty",
			"label": "Sourced Qty (Stock UOM)",
			"fieldtype": "Float",
			"insert_after": "sourcing_column",
			"read_only": 1,
			"description": "Quantity the rates and the promise were worked out for.",
		},
		{
			"fieldname": "sourced_qty_locked",
			"label": "Sourced Qty Fixed",
			"fieldtype": "Check",
			"insert_after": "sourced_stock_qty",
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "sourcing_request",
			"label": "Sourcing Request",
			"fieldtype": "Link",
			"options": "Sourcing Request",
			"insert_after": "sourced_qty_locked",
			"read_only": 1,
		},
		{
			"fieldname": "sourcing_request_item",
			"label": "Sourcing Request Item",
			"fieldtype": "Data",
			"insert_after": "sourcing_request",
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "estimated_landed_cost",
			"label": "Estimated Cost",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"insert_after": "sourcing_request_item",
			"read_only": 1,
			"permlevel": 1,
			"description": "Cost per stock UOM in company currency the rates are built on (landed cost; with the supplier minimum spread over this quantity when the customer bears it).",
		},
	]


def sourcing_link_fields(insert_after):
	"""Link to the Sourcing Request line, on purchasing documents."""
	return [
		{
			"fieldname": "sourcing_request",
			"label": "Sourcing Request",
			"fieldtype": "Link",
			"options": "Sourcing Request",
			"insert_after": insert_after,
			"read_only": 1,
			"search_index": 1,
		},
		{
			"fieldname": "sourcing_request_item",
			"label": "Sourcing Request Item",
			"fieldtype": "Data",
			"insert_after": "sourcing_request",
			"read_only": 1,
			"hidden": 1,
			"search_index": 1,
		},
	]


CUSTOM_FIELDS = {
	"Item": [
		{
			"fieldname": "purchase_order_multiple",
			"label": "Purchase Order Multiple",
			"fieldtype": "Float",
			"insert_after": "min_order_qty",
			"non_negative": 1,
			"description": "Suggested purchase quantities are rounded up to a multiple of this, in stock UOM (e.g. a carton of 12).",
		},
	],
	"Quotation": order_fields("valid_till")
	+ [
		{
			"fieldname": "sourcing_status",
			"label": "Sourcing Status",
			"fieldtype": "Select",
			"options": "\nPending Sourcing\nReady",
			"insert_after": "priority",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
			"in_standard_filter": 1,
		},
	],
	"Quotation Item": sourcing_item_fields(),
	"Sales Order": order_fields("delivery_date")
	+ [
		{
			"fieldname": "is_back_to_back",
			"label": "Is Back-to-Back",
			"fieldtype": "Check",
			"insert_after": "priority",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
			"in_standard_filter": 1,
		},
	],
	"Sales Order Item": sourcing_item_fields(),
	"Supplier": [
		{
			"fieldname": "landed_cost_percent",
			"label": "Landed Cost %",
			"fieldtype": "Percent",
			"insert_after": "default_currency",
			"non_negative": 1,
			"description": "Freight, customs and clearance as % of the purchase cost. Blank uses the planning settings default.",
		},
	],
	"Request for Quotation Item": sourcing_link_fields("material_request_item"),
	"Purchase Order Item": [
		{
			"fieldname": "is_excess",
			"label": "Supplier Minimum Excess",
			"fieldtype": "Check",
			"insert_after": "sales_order_item",
			"read_only": 1,
			"no_copy": 1,
			"description": "Quantity bought above a back-to-back customer order to meet the supplier minimum; goes to stock.",
		},
	],
	"Supplier Quotation Item": [
		{
			"fieldname": "min_order_qty",
			"label": "Supplier Min Order Qty",
			"fieldtype": "Float",
			"insert_after": "qty",
			"non_negative": 1,
			"description": "Minimum quantity the supplier sells, in this line's UOM.",
		},
	]
	+ sourcing_link_fields("material_request_item"),
	"Material Request": [
		{
			"fieldname": "procurement_type",
			"label": "Procurement Type",
			"fieldtype": "Select",
			"options": "\nPlanned\nBack-to-Back",
			"insert_after": "material_request_type",
			"allow_on_submit": 0,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "reorder_parameter_run",
			"label": "Reorder Parameter Run",
			"fieldtype": "Link",
			"options": "Reorder Parameter Run",
			"insert_after": "procurement_type",
			"read_only": 1,
		},
	],
	"Material Request Item": sourcing_link_fields("sales_order_item")
	+ [
		{
			"fieldname": "suggested_qty",
			"label": "Suggested Qty",
			"fieldtype": "Float",
			"insert_after": "qty",
			"read_only": 1,
			"description": "Quantity suggested by procurement planning, in stock UOM.",
		},
		{
			"fieldname": "variance_reason",
			"label": "Variance Reason",
			"fieldtype": "Select",
			"options": VARIANCE_REASONS,
			"insert_after": "suggested_qty",
			"description": "Why the requested quantity differs from the suggested quantity.",
		},
		{
			"fieldname": "suggested_supplier",
			"label": "Suggested Supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"insert_after": "variance_reason",
		},
		{
			"fieldname": "blanket_order",
			"label": "Blanket Order",
			"fieldtype": "Link",
			"options": "Blanket Order",
			"insert_after": "suggested_supplier",
			"read_only": 1,
			"description": "Purchasing agreement the item is requested under. The Purchase Order line is linked to it.",
		},
	],
}


# Fields of the first back-to-back design (supplier and offer on sales documents,
# sourcing through a Material Request), removed with their columns on migrate.
OBSOLETE_FIELDS = {
	"Quotation": ["sourcing_request"],
	"Quotation Item": [
		"supplier_quotation",
		"supplier_quotation_item",
		"sourcing_supplier",
		"purchase_qty",
		"excess_qty",
		"excess_pricing",
	],
	"Sales Order Item": [
		"supplier_quotation",
		"supplier_quotation_item",
		"sourcing_supplier",
		"purchase_qty",
		"excess_qty",
		"excess_pricing",
	],
	"Material Request Item": ["sales_quotation", "quotation_item"],
}

# Reports replaced by the sales / purchasing split.
OBSOLETE_REPORTS = ["Back-to-Back Tracker"]

# Standard fields that reveal the buying cost on sales documents: on permlevel 1,
# so only roles given level 1 on Quotation / Sales Order see them.
COST_FIELDS = {
	"Quotation Item": ["valuation_rate", "gross_profit"],
	"Sales Order Item": ["valuation_rate", "gross_profit"],
}


def after_install():
	make_custom_fields()


def after_migrate():
	make_custom_fields()


def make_custom_fields():
	remove_obsolete_fields()
	remove_obsolete_reports()
	create_custom_fields(CUSTOM_FIELDS, update=True)
	make_property_setters()
	backfill_submitted_on()


def remove_obsolete_fields():
	for doctype, fieldnames in OBSOLETE_FIELDS.items():
		for fieldname in fieldnames:
			name = frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fieldname})
			if name:
				frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
			# Deleting a Custom Field keeps its column; drop it so nothing reads stale data.
			# Never a column of a standard field.
			standard = frappe.db.exists("DocField", {"parent": doctype, "fieldname": fieldname})
			if not standard and frappe.db.has_column(doctype, fieldname):
				frappe.db.sql_ddl(f"alter table `tab{doctype}` drop column `{fieldname}`")
		frappe.clear_cache(doctype=doctype)


def remove_obsolete_reports():
	for name in OBSOLETE_REPORTS:
		if not frappe.db.exists("Report", {"name": name, "module": "Procurement Planning"}):
			continue
		# Report.on_trash refuses a standard report outside developer mode unless in a patch.
		in_patch = frappe.flags.in_patch
		frappe.flags.in_patch = True
		try:
			frappe.delete_doc("Report", name, ignore_permissions=True, force=True)
		finally:
			frappe.flags.in_patch = in_patch


def backfill_submitted_on():
	"""Sourcing Requests submitted before submitted_on existed: their last change
	is the best record of when."""
	if frappe.db.has_column("Sourcing Request", "submitted_on"):
		frappe.db.sql(
			"""update `tabSourcing Request` set submitted_on = modified
			where docstatus = 1 and submitted_on is null"""
		)


def make_property_setters():
	for doctype, fieldnames in COST_FIELDS.items():
		for fieldname in fieldnames:
			frappe.make_property_setter(
				{
					"doctype": doctype,
					"fieldname": fieldname,
					"property": "permlevel",
					"value": 1,
					"property_type": "Int",
				},
				validate_fields_for_doctype=False,
			)
