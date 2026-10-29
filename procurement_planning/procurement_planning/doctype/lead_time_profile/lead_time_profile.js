// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Lead Time Profile", {
	setup(frm) {
		frm.set_query("supplier", () => ({ filters: { disabled: 0 } }));
	},
});

frappe.ui.form.on("Lead Time Profile Entry", {
	entries_add(frm, cdt, cdn) {
		frappe.model.set_value(cdt, cdn, "from_date", frappe.datetime.get_today());
		frappe.model.set_value(cdt, cdn, "source", "Manual");
	},
});
