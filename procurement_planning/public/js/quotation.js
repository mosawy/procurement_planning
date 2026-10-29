// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Back-to-back sourcing on the Quotation form.

const B2B_API = "procurement_planning.planning.back_to_back";

frappe.ui.form.on("Quotation", {
	refresh(frm) {
		if (frm.is_new()) return;
		const group = __("Back-to-Back");
		const sourcing = (frm.doc.items || []).some((d) => d.needs_sourcing);

		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Request Sourcing"), () => request_sourcing(frm), group);
		}
		if (sourcing) {
			frm.add_custom_button(__("Supplier Offers"), () => show_supplier_offers(frm), group);
		}
		if (frm.doc.sourcing_request) {
			frm.add_custom_button(
				__("Sourcing Request"),
				() => frappe.set_route("Form", "Material Request", frm.doc.sourcing_request),
				group
			);
		}

		if (frm.doc.docstatus === 0 && frm.doc.sourcing_status === "Pending Sourcing") {
			frm.dashboard.set_headline(
				__("Some items need sourcing. Select a supplier offer for each before submitting.")
			);
		}
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

	frappe.confirm(
		__("Create a sourcing Material Request for {0} item(s)?", [items.length]),
		() =>
			frappe
				.call({
					method: `${B2B_API}.request_sourcing`,
					args: { quotation: frm.doc.name, items },
					freeze: true,
				})
				.then((r) => {
					frm.reload_doc();
					if (r.message) {
						frappe.msgprint(
							__("Material Request {0} created. Submit it, then make the Request for Quotation from it.", [
								frappe.utils.get_form_link("Material Request", r.message, true),
							])
						);
					}
				})
	);
}

function show_supplier_offers(frm) {
	const editable = frm.doc.docstatus === 0;
	const excess = {};
	let data = null;

	const dialog = new frappe.ui.Dialog({
		title: __("Supplier Offers"),
		size: "extra-large",
		fields: [
			{
				fieldname: "margin_percent",
				fieldtype: "Percent",
				label: __("Margin %"),
				description: __("Gross margin on the selling price."),
				hidden: !editable,
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "set_rate",
				fieldtype: "Check",
				label: __("Set rate from cost and margin"),
				default: 1,
				hidden: !editable,
			},
			{ fieldtype: "Section Break" },
			{ fieldname: "offers_html", fieldtype: "HTML" },
		],
		primary_action_label: editable ? __("Apply Selection") : __("Close"),
		primary_action() {
			if (!editable) {
				dialog.hide();
				return;
			}
			const selections = collect_selections(dialog, data);
			if (!selections.length) {
				frappe.msgprint(__("Select at least one offer."));
				return;
			}
			const values = dialog.get_values();
			selections.forEach((s) => {
				s.margin_percent = values.margin_percent;
				s.set_rate = values.set_rate ? 1 : 0;
			});
			const apply = () =>
				frappe
					.call({
						method: `${B2B_API}.select_offers`,
						args: { quotation: frm.doc.name, selections },
						freeze: true,
					})
					.then(() => {
						dialog.hide();
						frm.reload_doc();
						frappe.show_alert({ message: __("Supplier offers applied"), indicator: "green" });
					});

			const no_lead_time = rows_without_lead_time(data, selections);
			if (no_lead_time.length) {
				frappe.confirm(
					__(
						"The offers for rows {0} have no lead time, so no date can be promised to the customer and the Purchase Order falls back to the Sales Order delivery date. Apply anyway?",
						[no_lead_time.join(", ")]
					),
					apply
				);
			} else {
				apply();
			}
		},
	});

	const load = () => {
		const checked = data ? collect_selections(dialog, data) : [];
		frappe
			.call({
				method: `${B2B_API}.get_supplier_offers`,
				args: { quotation: frm.doc.name, excess_pricing: excess },
			})
			.then((r) => {
				const first = !data;
				data = r.message;
				if (first) dialog.set_value("margin_percent", data.default_margin_percent);
				render_offers(dialog, data, editable, checked);
			});
	};

	dialog.fields_dict.offers_html.$wrapper.on("change", "select.b2b-excess", function () {
		excess[$(this).attr("data-line")] = $(this).val();
		load();
	});

	dialog.show();
	load();
}

function collect_selections(dialog, data) {
	const $wrapper = dialog.fields_dict.offers_html.$wrapper;
	const selections = [];
	(data.lines || []).forEach((line) => {
		const value = $wrapper.find(`input[name="b2b-offer-${line.quotation_item}"]:checked`).val();
		if (value) {
			selections.push({
				quotation_item: line.quotation_item,
				supplier_quotation_item: value,
				excess_pricing: $wrapper.find(`select[data-line="${line.quotation_item}"]`).val(),
			});
		}
	});
	return selections;
}

function rows_without_lead_time(data, selections) {
	const rows = [];
	selections.forEach((s) => {
		const line = data.lines.find((l) => l.quotation_item === s.quotation_item);
		const offer = line && line.offers.find((o) => o.supplier_quotation_item === s.supplier_quotation_item);
		if (offer && (offer.lead_time_days === null || offer.lead_time_days === undefined)) rows.push(line.idx);
	});
	return rows;
}

function render_offers(dialog, data, editable, checked) {
	const esc = frappe.utils.escape_html;
	const kept = {};
	(checked || []).forEach((s) => (kept[s.quotation_item] = s.supplier_quotation_item));
	const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
	const company_money = (value) =>
		value === null || value === undefined ? "" : format_currency(value, data.company_currency);

	let html = "";
	if (!data.lines.length) {
		html = `<p class="text-muted">${__("No line needs sourcing.")}</p>`;
	}
	if (data.priority) {
		html += `<p class="text-muted">${__("Priority {0}: offers ranked by {1}.", [
			esc(data.priority),
			data.priority === "Urgent" ? __("earliest promise") : __("cost"),
		])}</p>`;
	}

	data.lines.forEach((line) => {
		const selected = kept[line.quotation_item] || line.selected;
		const options = ["Excess to Stock", "Customer Bears Excess"]
			.map((o) => `<option value="${o}" ${o === line.excess_pricing ? "selected" : ""}>${__(o)}</option>`)
			.join("");

		html += `<div class="b2b-line" style="margin-bottom: 1.5rem">
			<div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap">
				<strong>${__("Row {0}", [line.idx])}: ${esc(line.item_code)} &mdash; ${esc(line.item_name || "")}
					(${line.qty} ${esc(line.uom || "")}, ${line.stock_qty} ${esc(line.stock_uom || "")})</strong>
				<label class="small">${__("Supplier minimum above need")}:
					<select class="b2b-excess form-control input-xs" style="display: inline-block; width: auto"
						data-line="${esc(line.quotation_item)}" ${editable ? "" : "disabled"}>${options}</select>
				</label>
			</div>`;

		if (!line.offers.length) {
			html += `<p class="text-muted">${__("No submitted supplier offer yet.")}</p></div>`;
			return;
		}

		html += `<div class="table-responsive"><table class="table table-bordered table-condensed small">
			<thead><tr>
				<th></th>
				<th>${__("Supplier")}</th>
				<th>${__("Offer")}</th>
				<th class="text-right">${__("Offer Rate")}</th>
				<th class="text-right">${__("Unit Cost")}</th>
				<th class="text-right">${__("Landed Cost")}</th>
				<th class="text-right">${__("Supplier MOQ")}</th>
				<th class="text-right">${__("Buy / Excess")}</th>
				<th class="text-right">${__("Customer Unit Cost")}</th>
				<th class="text-right">${__("Lead Days")}</th>
				<th>${__("Promise")}</th>
				<th>${__("Valid Till")}</th>
			</tr></thead><tbody>`;

		line.offers.forEach((offer, index) => {
			const flags = [];
			if (index === 0 && !offer.expired) flags.push(`<span class="indicator-pill green">${__("Best")}</span>`);
			if (offer.linked) flags.push(`<span class="indicator-pill blue">${__("Requested")}</span>`);
			if (offer.expired) flags.push(`<span class="indicator-pill red">${__("Expired")}</span>`);
			const no_lead_time = offer.lead_time_days === null || offer.lead_time_days === undefined;
			if (no_lead_time) flags.push(`<span class="indicator-pill orange">${__("No lead time")}</span>`);
			const is_selected = offer.supplier_quotation_item === selected;

			html += `<tr class="${is_selected ? "table-active" : ""}">
				<td><input type="radio" name="b2b-offer-${esc(line.quotation_item)}"
					value="${esc(offer.supplier_quotation_item)}" ${is_selected ? "checked" : ""}
					${editable ? "" : "disabled"}></td>
				<td>${esc(offer.supplier_name || offer.supplier)} ${flags.join(" ")}</td>
				<td><a href="/app/supplier-quotation/${encodeURIComponent(offer.supplier_quotation)}" target="_blank">${esc(
					offer.supplier_quotation
				)}</a></td>
				<td class="text-right">${format_currency(offer.rate, offer.currency)} / ${esc(offer.uom || "")}</td>
				<td class="text-right">${company_money(offer.unit_cost)}</td>
				<td class="text-right" title="${__("Landed {0}%", [offer.landed_cost_percent])}">${company_money(
					offer.landed_cost
				)}</td>
				<td class="text-right">${offer.min_order_qty || ""}</td>
				<td class="text-right">${offer.purchase_qty} / ${offer.excess_qty}</td>
				<td class="text-right"><strong>${company_money(offer.customer_unit_cost)}</strong></td>
				<td class="text-right">${offer.lead_time_days === null ? "" : offer.lead_time_days}</td>
				<td>${
					no_lead_time
						? `<span class="text-warning" title="${__(
								"Set Lead Time in days or Expected Delivery Date on the Supplier Quotation"
						  )}">${__("No promise")}</span>`
						: date(offer.promised_date)
				}</td>
				<td>${date(offer.valid_till)}</td>
			</tr>`;
		});
		html += `</tbody></table></div></div>`;
	});

	html += `<p class="text-muted small">${__(
		"Costs are per stock UOM in {0}. Landed cost adds the supplier's landed cost % (or the settings default) and, for foreign currency, the FX buffer.",
		[esc(data.company_currency)]
	)}</p>`;

	dialog.fields_dict.offers_html.$wrapper.html(html);
}
