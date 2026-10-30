# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Custom fields this app adds to standard ERPNext DocTypes.

Created on install and refreshed on every migrate, so the definitions live in
code rather than in exported fixtures.
"""

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
EXCESS_PRICING = "\nCustomer Bears Excess\nExcess to Stock"


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
	"""Back-to-back sourcing fields on Quotation Item and Sales Order Item (same
	names, so the standard mapping copies them)."""
	return [
		{
			"fieldname": "needs_sourcing",
			"label": "Needs Sourcing",
			"fieldtype": "Check",
			"insert_after": "item_name",
			"in_list_view": 0,
			"description": "Bought back-to-back for this order from a supplier offer.",
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
			"fieldname": "supplier_quotation",
			"label": "Supplier Quotation",
			"fieldtype": "Link",
			"options": "Supplier Quotation",
			"insert_after": "sourcing_section",
			"read_only": 1,
		},
		{
			"fieldname": "supplier_quotation_item",
			"label": "Supplier Quotation Item",
			"fieldtype": "Data",
			"insert_after": "supplier_quotation",
			"read_only": 1,
			"hidden": 1,
		},
		{
			"fieldname": "sourcing_supplier",
			"label": "Sourcing Supplier",
			"fieldtype": "Link",
			"options": "Supplier",
			"insert_after": "supplier_quotation_item",
			"read_only": 1,
		},
		{
			"fieldname": "estimated_landed_cost",
			"label": "Estimated Landed Cost",
			"fieldtype": "Currency",
			"options": "Company:company:default_currency",
			"insert_after": "sourcing_supplier",
			"read_only": 1,
			"description": "Per stock UOM, company currency: supplier cost plus landed cost % and FX buffer.",
		},
		{
			"fieldname": "promised_date",
			"label": "Promised Date",
			"fieldtype": "Date",
			"insert_after": "estimated_landed_cost",
			"description": "Date promised to the customer: offer lead time plus delivery buffer.",
		},
		{
			"fieldname": "sourcing_column",
			"fieldtype": "Column Break",
			"insert_after": "promised_date",
		},
		{
			"fieldname": "purchase_qty",
			"label": "Purchase Qty",
			"fieldtype": "Float",
			"insert_after": "sourcing_column",
			"read_only": 1,
			"description": "Stock UOM: the larger of the need and the supplier minimum order.",
		},
		{
			"fieldname": "excess_qty",
			"label": "Excess Qty",
			"fieldtype": "Float",
			"insert_after": "purchase_qty",
			"read_only": 1,
		},
		{
			"fieldname": "excess_pricing",
			"label": "Excess Pricing",
			"fieldtype": "Select",
			"options": EXCESS_PRICING,
			"insert_after": "excess_qty",
			"read_only": 1,
		},
		{
			"fieldname": "quote_valid_till",
			"label": "Supplier Offer Valid Till",
			"fieldtype": "Date",
			"insert_after": "excess_pricing",
			"read_only": 1,
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
			"options": "\nPending Sourcing\nReady for Pricing",
			"insert_after": "priority",
			"read_only": 1,
			"no_copy": 1,
			"allow_on_submit": 1,
			"in_standard_filter": 1,
		},
		{
			"fieldname": "sourcing_request",
			"label": "Sourcing Request",
			"fieldtype": "Link",
			"options": "Material Request",
			"insert_after": "sourcing_status",
			"read_only": 1,
			"no_copy": 1,
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
	"Supplier Quotation Item": [
		{
			"fieldname": "min_order_qty",
			"label": "Supplier Min Order Qty",
			"fieldtype": "Float",
			"insert_after": "qty",
			"non_negative": 1,
			"description": "Minimum quantity the supplier sells, in this line's UOM.",
		},
	],
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
	"Material Request Item": [
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
		{
			"fieldname": "sales_quotation",
			"label": "Sales Quotation",
			"fieldtype": "Link",
			"options": "Quotation",
			"insert_after": "sales_order_item",
			"read_only": 1,
			"search_index": 1,
		},
		{
			"fieldname": "quotation_item",
			"label": "Quotation Item",
			"fieldtype": "Data",
			"insert_after": "sales_quotation",
			"read_only": 1,
			"hidden": 1,
		},
	],
}


def after_install():
	make_custom_fields()


def after_migrate():
	make_custom_fields()


def make_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)
