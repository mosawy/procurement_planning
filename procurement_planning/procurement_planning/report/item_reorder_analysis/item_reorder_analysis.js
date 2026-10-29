// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.query_reports["Item Reorder Analysis"] = {
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
			fieldname: "item_group",
			label: __("Item Group"),
			fieldtype: "Link",
			options: "Item Group",
		},
		{
			fieldname: "analysis_months",
			label: __("Analysis Months"),
			fieldtype: "Int",
			default: 12,
			reqd: 1,
		},
	],
};
