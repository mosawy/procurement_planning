// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Procurement Planning Settings", {
	setup(frm) {
		frm.set_query("default_purchase_warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Derive Lead Times"), () => {
			frappe.confirm(
				__(
					"Calculate lead times per supplier and per supplier + brand from received Purchase Orders, and add them to Lead Time Profiles? Manual entries are never overwritten."
				),
				() =>
					frappe.call({
						method: "procurement_planning.planning.api.derive_lead_times",
						args: { company: frm.doc.company },
						freeze: true,
						freeze_message: __("Deriving lead times..."),
						callback: (r) => r.message && show_derivation_summary(r.message),
					})
			);
		});

		frm.add_custom_button(__("Lead Time Profiles"), () =>
			frappe.set_route("List", "Lead Time Profile", { company: frm.doc.company })
		);
		frm.add_custom_button(__("Planning Screen"), () => frappe.set_route("procurement-planning"));
	},
});

function show_derivation_summary(summary) {
	const rows = [
		[__("Received Purchase Orders analysed"), summary.samples],
		[__("Lead times found (enough orders)"), summary.groups],
		[__("Profiles created"), summary.created],
		[__("Profiles updated with a new entry"), summary.updated],
		[__("Unchanged"), summary.unchanged],
		[__("Skipped: latest entry is manual"), summary.skipped_manual],
	];
	frappe.msgprint({
		title: __("Lead Times Derived"),
		indicator: "green",
		message: `<p>${__("Period {0} to {1}, at least {2} orders per lead time.", [
			frappe.datetime.str_to_user(summary.from_date),
			frappe.datetime.str_to_user(summary.to_date),
			summary.min_samples,
		])}</p><table class="table table-bordered table-sm">${rows
			.map(([label, value]) => `<tr><td>${label}</td><td class="text-right">${value}</td></tr>`)
			.join("")}</table>`,
	});
}
