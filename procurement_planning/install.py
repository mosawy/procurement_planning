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
	],
}


def after_install():
	make_custom_fields()


def after_migrate():
	make_custom_fields()


def make_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, update=True)
