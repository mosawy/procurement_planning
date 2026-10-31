// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back sourcing on the Quotation form. Sales sees only the price and
// promise purchasing returns, never the supplier or the cost.

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		set_sourcing_headline(frm);
	},
});

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
