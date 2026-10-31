// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Sourcing Request", {
	refresh(frm) {
		if (frm.is_new()) return;
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(
				__("Request for Quotation"),
				() =>
					frappe.model.open_mapped_doc({
						method: "procurement_planning.procurement_planning.doctype.sourcing_request.sourcing_request.make_request_for_quotation",
						frm,
					}),
				__("Create")
			);
		}
	},
});
