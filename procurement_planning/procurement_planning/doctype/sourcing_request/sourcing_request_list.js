// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.listview_settings["Sourcing Request"] = {
	add_fields: ["status"],
	onload(listview) {
		// The dashboard shows cost and margin: only for users the page is open to.
		if ((frappe.boot.page_info || {})["back-to-back-dashboard"]) {
			listview.page.add_inner_button(__("Back-to-Back Dashboard"), () => frappe.set_route("back-to-back-dashboard"));
		}
	},
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
