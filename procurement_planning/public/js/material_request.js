// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back Material Request: Purchase Orders at the offers chosen on the
// Sourcing Requests.

frappe.ui.form.on("Material Request", {
	refresh(frm) {
		const doc = frm.doc;
		if (doc.docstatus !== 1 || doc.procurement_type !== "Back-to-Back") return;
		if (["Stopped", "Closed", "Ordered"].includes(doc.status)) return;
		frm.add_custom_button(
			__("Back-to-Back Purchase Orders"),
			() => make_back_to_back_purchase_orders(frm),
			__("Create")
		);
	},
});

function make_back_to_back_purchase_orders(frm) {
	frappe.confirm(__("Create draft Purchase Orders at the chosen supplier offers?"), () =>
		frappe
			.call({
				method: "procurement_planning.planning.back_to_back.make_back_to_back_purchase_orders",
				args: { material_request: frm.doc.name },
				freeze: true,
			})
			.then((r) => {
				const res = r.message || {};
				const created = res.purchase_orders || [];
				const list = (title, rows) =>
					rows.length ? `<br><br>${title}<br>${rows.map(frappe.utils.escape_html).join("<br>")}` : "";
				const message =
					(created.length
						? __("Draft Purchase Orders created: {0}", [
								created.map((name) => frappe.utils.get_form_link("Purchase Order", name, true)).join(", "),
						  ])
						: __("No Purchase Order created.")) +
					list(__("Check:"), res.warnings || []) +
					list(__("Skipped:"), res.skipped || []);
				frappe.msgprint({
					title: __("Back-to-Back Purchase Orders"),
					message,
					indicator: created.length ? "green" : "orange",
				});
				frm.reload_doc();
			})
	);
}
