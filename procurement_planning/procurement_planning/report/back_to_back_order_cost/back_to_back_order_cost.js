// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Back-to-Back Order Cost"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{
			fieldname: "sales_order",
			label: __("Sales Order"),
			fieldtype: "Link",
			options: "Sales Order",
			get_query: () => ({ filters: { docstatus: 1 } }),
		},
		{ fieldname: "customer", label: __("Customer"), fieldtype: "Link", options: "Customer" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
	],
	tree: true,
	name_field: "id",
	parent_field: "parent_id",
	initial_depth: 1,
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "variance" && data.variance > 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		if (column.fieldname === "margin" && data.margin !== null && data.margin < 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		if (data.indent === 0 && column.fieldname === "reference") {
			value = `<strong>${value}</strong>`;
		}
		return value;
	},
};
