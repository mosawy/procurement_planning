// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back purchasing on the Sales Order form.

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		const group = __("Back-to-Back");
		const sourcing = (frm.doc.items || []).some((d) => d.needs_sourcing);
		if (!sourcing && !frm.doc.is_back_to_back) return;

		if (frm.doc.docstatus === 1) {
			frm.add_custom_button(
				__("Order Cost"),
				() => frappe.set_route("query-report", "Back-to-Back Order Cost", { sales_order: frm.doc.name }),
				group
			);
			frm.add_custom_button(
				__("Tracker"),
				() => frappe.set_route("query-report", "Back-to-Back Tracker", { sales_order: frm.doc.name }),
				group
			);
		}
	},
});
