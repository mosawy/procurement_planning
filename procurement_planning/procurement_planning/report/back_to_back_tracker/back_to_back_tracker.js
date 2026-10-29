// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Back-to-Back Tracker"] = {
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
		{
			fieldname: "priority",
			label: __("Priority"),
			fieldtype: "Select",
			options: ["", "Urgent", "Normal", "Flexible"],
		},
		{
			fieldname: "stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: ["", "Not Ordered", "PO Draft", "Ordered", "Shipped", "Partly Received", "Received", "Delivered"],
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "show_completed", label: __("Show Delivered"), fieldtype: "Check", default: 0 },
	],
	formatter(value, row, column, data, default_formatter) {
		value = default_formatter(value, row, column, data);
		if (!data) return value;
		if (column.fieldname === "days_late" && data.days_late !== null && data.days_late !== undefined) {
			const color = data.days_late > 0 ? "var(--red-600)" : "var(--green-600)";
			value = `<span style="color: ${color}">${value}</span>`;
		}
		if (column.fieldname === "priority" && data.priority === "Urgent") {
			value = `<strong style="color: var(--orange-600)">${value}</strong>`;
		}
		return value;
	},
};
