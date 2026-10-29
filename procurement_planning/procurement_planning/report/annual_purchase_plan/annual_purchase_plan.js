// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Annual Purchase Plan"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			reqd: 1,
		},
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{
			fieldname: "blanket_order",
			label: __("Blanket Order"),
			fieldtype: "Link",
			options: "Blanket Order",
			get_query: () => ({ filters: { blanket_order_type: "Purchasing" } }),
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date", default: frappe.datetime.year_start() },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date", default: frappe.datetime.year_end() },
		{ fieldname: "include_drafts", label: __("Include Drafts"), fieldtype: "Check", default: 1 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (column.fieldname === "remaining_qty" && data && data.remaining_qty < 0) {
			value = `<span style="color: var(--red-600)">${value}</span>`;
		}
		return value;
	},
};
