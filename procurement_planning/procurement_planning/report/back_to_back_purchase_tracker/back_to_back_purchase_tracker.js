// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Back-to-Back Purchase Tracker"] = {
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
			fieldname: "material_request",
			label: __("Material Request"),
			fieldtype: "Link",
			options: "Material Request",
			get_query: () => ({ filters: { procurement_type: "Back-to-Back" } }),
		},
		{ fieldname: "sourcing_request", label: __("Sourcing Request"), fieldtype: "Link", options: "Sourcing Request" },
		{ fieldname: "supplier", label: __("Supplier"), fieldtype: "Link", options: "Supplier" },
		{
			fieldname: "stage",
			label: __("Stage"),
			fieldtype: "Select",
			options: ["", "MR Draft", "Not Ordered", "PO Draft", "Ordered", "Shipped", "Partly Received", "Received"],
		},
		{ fieldname: "from_date", label: __("From Date"), fieldtype: "Date" },
		{ fieldname: "to_date", label: __("To Date"), fieldtype: "Date" },
		{ fieldname: "show_completed", label: __("Show Received"), fieldtype: "Check", default: 0 },
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
