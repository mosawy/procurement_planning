// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.ui.form.on("Reorder Parameter Run", {
	setup(frm) {
		frappe.realtime.on("reorder_parameter_run_calculated", (data) => {
			if (!data || data.run !== frm.doc.name) return;
			frappe.show_alert({
				message: data.failed ? __("Calculation failed. See the Error Log.") : __("Parameters calculated"),
				indicator: data.failed ? "red" : "green",
			});
			frm.reload_doc();
		});
	},

	refresh(frm) {
		if (frm.is_new()) return;
		const doc = frm.doc;

		if (doc.docstatus === 0 && doc.status !== "Calculating") {
			frm.add_custom_button(
				doc.total_items ? __("Recalculate") : __("Calculate Parameters"),
				() =>
					frm.call("calculate").then((r) => {
						if (r.message) frappe.show_alert({ message: r.message, indicator: "blue" });
						frm.reload_doc();
					})
			);
		}

		if (doc.total_items) {
			frm.add_custom_button(__("Review Lines"), () => {
				frappe.route_options = { run: doc.name };
				frappe.set_route("List", "Reorder Parameter Line", "Report");
			});
		}

		if (doc.docstatus === 1) {
			frm.add_custom_button(__("Create Annual Plan"), () => create_annual_plan(frm));
			frm.add_custom_button(__("Planning Screen"), () => frappe.set_route("procurement-planning"));
		}

		show_status(frm);
	},
});

function show_status(frm) {
	const doc = frm.doc;
	if (doc.status === "Calculating") {
		frm.dashboard.set_headline(__("Calculating parameters in the background. This form refreshes when it finishes."));
		return;
	}
	if (!doc.total_items) {
		if (doc.docstatus === 0) frm.dashboard.set_headline(__("Click Calculate Parameters to build the lines."));
		return;
	}

	frm.call("get_summary").then((r) => {
		const s = r.message || {};
		const parts = [
			__("{0} items", [s.total || 0]),
			__("{0} overridden", [s.overridden || 0]),
			__("{0} with a change of 50% or more", [s.big_changes || 0]),
			__("{0} suppliers inferred from the latest PO", [s.inferred_suppliers || 0]),
			__("{0} without supplier", [s.no_supplier || 0]),
			__("{0} using a default or no lead time", [s.weak_lead_time || 0]),
		];
		frm.dashboard.set_headline(parts.join(" · "));
	});
}

function create_annual_plan(frm) {
	const year = frappe.datetime.str_to_obj(frm.doc.analysis_date).getFullYear();
	const dialog = new frappe.ui.Dialog({
		title: __("Create Annual Plan"),
		fields: [
			{
				fieldtype: "HTML",
				options: `<p class="text-muted">${__(
					"Creates one draft Purchasing Blanket Order per supplier, with each item's planned quantity = average monthly sales × months in the period, at the last purchase rate. Lines without a supplier are skipped."
				)}</p>`,
			},
			{ fieldname: "from_date", fieldtype: "Date", label: __("From Date"), reqd: 1, default: `${year}-01-01` },
			{ fieldname: "to_date", fieldtype: "Date", label: __("To Date"), reqd: 1, default: `${year}-12-31` },
		],
		primary_action_label: __("Create Drafts"),
		primary_action(values) {
			frappe.call({
				method: "procurement_planning.planning.annual_plan.create_annual_plan",
				args: { run: frm.doc.name, from_date: values.from_date, to_date: values.to_date },
				freeze: true,
				freeze_message: __("Creating Blanket Orders..."),
				callback(r) {
					dialog.hide();
					const res = r.message || {};
					const created = (res.created || []).map((name) => `<li>${frappe.utils.get_form_link("Blanket Order", name, true)}</li>`).join("");
					const skipped = (res.skipped || []).map((s) => `<li>${frappe.utils.escape_html(s)}</li>`).join("");
					frappe.msgprint({
						title: __("Annual Plan"),
						indicator: "green",
						message: `<p>${__("{0} draft Blanket Orders created.", [(res.created || []).length])}</p>${created ? `<ul>${created}</ul>` : ""}${
							skipped ? `<p>${__("Skipped")}:</p><ul>${skipped}</ul>` : ""
						}`,
					});
				},
			});
		},
	});
	dialog.show();
}
