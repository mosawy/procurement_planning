// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back purchasing on the Sales Order form.

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		const group = __("Back-to-Back");
		const sourcing = (frm.doc.items || []).some((d) => d.needs_sourcing);
		if (!sourcing && !frm.doc.is_back_to_back) return;

		if (frm.doc.docstatus === 1 && sourcing && !["Closed", "On Hold", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Create Back-to-Back POs"), () => make_purchase_orders(frm), group);
		}

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

function make_purchase_orders(frm) {
	frappe.confirm(__("Create draft Purchase Orders for the back-to-back lines of this Sales Order?"), () =>
		frappe
			.call({
				method: "procurement_planning.planning.back_to_back.make_back_to_back_purchase_orders",
				args: { sales_order: frm.doc.name },
				freeze: true,
			})
			.then((r) => {
				const result = r.message || {};
				const created = result.purchase_orders || [];
				const skipped = result.skipped || [];
				let message = created.length
					? __("Draft Purchase Orders created: {0}", [
							created.map((name) => frappe.utils.get_form_link("Purchase Order", name, true)).join(", "),
					  ])
					: __("No Purchase Order created.");
				if (skipped.length) {
					message += "<br><br>" + __("Skipped:") + "<br>" + skipped.map(frappe.utils.escape_html).join("<br>");
				}
				frappe.msgprint({ title: __("Back-to-Back Purchase Orders"), message, indicator: created.length ? "green" : "orange" });
				frm.reload_doc();
			})
	);
}
