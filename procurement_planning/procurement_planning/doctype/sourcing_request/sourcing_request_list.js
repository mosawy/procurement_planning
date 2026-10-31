// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.listview_settings["Sourcing Request"] = {
	add_fields: ["status"],
	get_indicator(doc) {
		const colors = {
			Draft: "red",
			"Waiting for Offers": "orange",
			Ready: "blue",
			Submitted: "green",
			Cancelled: "gray",
		};
		return [__(doc.status), colors[doc.status] || "gray", "status,=," + doc.status];
	},
};
