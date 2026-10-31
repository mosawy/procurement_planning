// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back sourcing on the Quotation form. Sales sees only the price and
// promise purchasing returns, never the supplier or the cost.

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		set_sourcing_headline(frm);
		if (frm.is_new() || frm.doc.docstatus !== 0) return;
		frm.add_custom_button(__("Request Sourcing"), () => request_sourcing(frm), __("Back-to-Back"));
	},
});

function request_sourcing(frm) {
	if (frm.is_dirty()) {
		frappe.msgprint(__("Save the Quotation first."));
		return;
	}
	const selected = frm.fields_dict.items.grid.get_selected_children().map((d) => d.name);
	const marked = (frm.doc.items || []).filter((d) => d.needs_sourcing).map((d) => d.name);
	const items = selected.length ? selected : marked;
	if (!items.length) {
		frappe.msgprint(__("Select the item rows to source, or tick Needs Sourcing on them."));
		return;
	}

	frappe.confirm(__("Send {0} item(s) to purchasing for a price?", [items.length]), () =>
		frappe
			.call({
				method: "procurement_planning.planning.back_to_back.request_sourcing",
				args: { quotation: frm.doc.name, items },
				freeze: true,
			})
			.then((r) => {
				const res = r.message || {};
				frm.reload_doc();
				let message = __("Sourcing Request {0} sent to purchasing with {1} item(s). You will be notified when the prices are ready.", [
					res.sourcing_request,
					res.lines,
				]);
				if (res.skipped) message += "<br>" + __("{0} item(s) were already with purchasing.", [res.skipped]);
				frappe.msgprint(message);
			})
	);
}

function set_sourcing_headline(frm) {
	// layout.show_message appends, so remove our own block first; other headlines stay
	const $message = frm.layout.message;
	$message.find(".b2b-sourcing-headline").remove();
	if (!$message.children().length) frm.dashboard.clear_headline();

	if (frm.doc.docstatus === 0 && frm.doc.sourcing_status === "Pending Sourcing") {
		frm.dashboard.set_headline(
			`<div class="b2b-sourcing-headline">${__(
				"Some items are waiting for a price from purchasing. Submit is possible once every one has a price."
			)}</div>`
		);
	}
}
