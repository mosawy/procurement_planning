// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back purchasing on the Sales Order form: sales hands the sourced
// lines to purchasing as a Material Request, without supplier or cost data.

frappe.ui.form.on("Sales Order", {
	refresh(frm) {
		if (frm.is_new()) return;
		const group = __("Back-to-Back");
		const sourcing = (frm.doc.items || []).some((d) => d.needs_sourcing);
		if (!sourcing && !frm.doc.is_back_to_back) return;

		const sourced = (frm.doc.items || []).some((d) => d.needs_sourcing && d.sourcing_request_item);
		if (frm.doc.docstatus === 1 && sourced && !["Closed", "On Hold", "Completed"].includes(frm.doc.status)) {
			frm.add_custom_button(__("Request Purchase"), () => request_purchase(frm), group);
		}

		if (frm.doc.docstatus === 1) {
			// Order Cost shows buying cost: only for users the report is open to.
			if ((frappe.boot.user.all_reports || {})["Back-to-Back Order Cost"]) {
				frm.add_custom_button(
					__("Order Cost"),
					() => frappe.set_route("query-report", "Back-to-Back Order Cost", { sales_order: frm.doc.name }),
					group
				);
			}
			frm.add_custom_button(
				__("Tracker"),
				() => frappe.set_route("query-report", "Back-to-Back Sales Tracker", { sales_order: frm.doc.name }),
				group
			);
		}
	},
});

function request_purchase(frm) {
	frappe.confirm(__("Send the back-to-back lines of this Sales Order to purchasing as a Material Request?"), () =>
		frappe
			.call({
				method: "procurement_planning.planning.back_to_back.request_purchase",
				args: { sales_order: frm.doc.name },
				freeze: true,
			})
			.then((r) => {
				const res = r.message || {};
				let message = __("Material Request {0} created with {1} line(s); it goes through the usual approval.", [
					res.material_request,
					res.lines,
				]);
				if ((res.skipped || []).length) {
					message += "<br><br>" + __("Skipped:") + "<br>" + res.skipped.map(frappe.utils.escape_html).join("<br>");
				}
				frappe.msgprint({ title: __("Request Purchase"), message, indicator: "green" });
				frm.reload_doc();
			})
	);
}
