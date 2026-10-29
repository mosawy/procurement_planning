// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.listview_settings["Reorder Parameter Run"] = {
	add_fields: ["status", "is_active"],
	get_indicator(doc) {
		if (doc.status === "Approved" && doc.is_active) return [__("Active"), "green", "is_active,=,1"];
		const colors = { Draft: "red", Calculating: "orange", Ready: "blue", Approved: "gray", Cancelled: "darkgrey" };
		return [__(doc.status), colors[doc.status] || "gray", `status,=,${doc.status}`];
	},
};
