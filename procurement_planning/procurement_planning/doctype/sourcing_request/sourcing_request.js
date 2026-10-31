// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

const SOURCING_API = "procurement_planning.planning.back_to_back";

frappe.ui.form.on("Sourcing Request", {
	refresh(frm) {
		if (frm.is_new()) return;
		frm.add_custom_button(__("Supplier Offers"), () => show_supplier_offers(frm));
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

function show_supplier_offers(frm) {
	const editable = frm.doc.docstatus === 0;
	const excess = {};
	let data = null;

	const dialog = new frappe.ui.Dialog({
		title: __("Supplier Offers"),
		size: "extra-large",
		fields: [{ fieldname: "offers_html", fieldtype: "HTML" }],
		primary_action_label: editable ? __("Apply Selection") : __("Close"),
		primary_action() {
			if (!editable) {
				dialog.hide();
				return;
			}
			if (frm.is_dirty()) {
				frappe.msgprint(__("Save the Sourcing Request first."));
				return;
			}
			const selections = collect_selections(dialog, data);
			if (!selections.length) {
				frappe.msgprint(__("Select at least one offer."));
				return;
			}
			const apply = () =>
				frappe
					.call({
						method: `${SOURCING_API}.select_offers`,
						args: { sourcing_request: frm.doc.name, selections },
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
				method: `${SOURCING_API}.get_supplier_offers`,
				args: { sourcing_request: frm.doc.name, excess_pricing: excess },
			})
			.then((r) => {
				data = r.message;
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
		const value = $wrapper.find(`input[name="b2b-offer-${line.name}"]:checked`).val();
		if (value) {
			selections.push({
				name: line.name,
				supplier_quotation_item: value,
				excess_pricing: $wrapper.find(`select[data-line="${line.name}"]`).val(),
			});
		}
	});
	return selections;
}

function rows_without_lead_time(data, selections) {
	const rows = [];
	selections.forEach((s) => {
		const line = data.lines.find((l) => l.name === s.name);
		const offer = line && line.offers.find((o) => o.supplier_quotation_item === s.supplier_quotation_item);
		if (offer && (offer.lead_time_days === null || offer.lead_time_days === undefined)) rows.push(line.idx);
	});
	return rows;
}

function render_offers(dialog, data, editable, checked) {
	const esc = frappe.utils.escape_html;
	const kept = {};
	(checked || []).forEach((s) => (kept[s.name] = s.supplier_quotation_item));
	const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
	const money = (value) => (value === null || value === undefined ? "" : format_currency(value, data.company_currency));

	let html = `<p class="text-muted">${__("Margin {0}%. ", [data.margin_percent])}${
		data.priority
			? __("Priority {0}: offers ranked by {1}.", [
					esc(data.priority),
					data.priority === "Urgent" ? __("earliest promise") : __("cost"),
			  ])
			: __("Offers ranked by cost.")
	}</p>`;

	data.lines.forEach((line) => {
		const selected = kept[line.name] || line.selected;
		const options = ["Excess to Stock", "Customer Bears Excess"]
			.map((o) => `<option value="${o}" ${o === line.excess_pricing ? "selected" : ""}>${__(o)}</option>`)
			.join("");

		html += `<div style="margin-bottom: 1.5rem">
			<div style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; flex-wrap: wrap">
				<strong>${__("Row {0}", [line.idx])}: ${esc(line.item_code)} &mdash; ${esc(line.item_name || "")}
					(${line.qty} ${esc(line.uom || "")}, ${line.stock_qty} ${esc(line.stock_uom || "")})</strong>
				<label class="small">${__("Supplier minimum above need")}:
					<select class="b2b-excess form-control input-xs" style="display: inline-block; width: auto"
						data-line="${esc(line.name)}" ${editable ? "" : "disabled"}>${options}</select>
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
				<th class="text-right">${__("Pricing Cost")}</th>
				<th class="text-right">${__("Suggested / Minimum Rate")}</th>
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
				<td><input type="radio" name="b2b-offer-${esc(line.name)}"
					value="${esc(offer.supplier_quotation_item)}" ${is_selected ? "checked" : ""}
					${editable ? "" : "disabled"}></td>
				<td>${esc(offer.supplier_name || offer.supplier)} ${flags.join(" ")}</td>
				<td><a href="/app/supplier-quotation/${encodeURIComponent(offer.supplier_quotation)}" target="_blank">${esc(
					offer.supplier_quotation
				)}</a></td>
				<td class="text-right">${format_currency(offer.rate, offer.currency)} / ${esc(offer.uom || "")}</td>
				<td class="text-right">${money(offer.unit_cost)}</td>
				<td class="text-right" title="${__("Landed {0}%", [offer.landed_cost_percent])}">${money(offer.landed_cost)}</td>
				<td class="text-right">${offer.min_order_qty || ""}</td>
				<td class="text-right">${offer.purchase_qty} / ${offer.excess_qty}</td>
				<td class="text-right"><strong>${money(offer.customer_unit_cost)}</strong></td>
				<td class="text-right">${money(offer.suggested_rate)} / ${money(offer.minimum_rate)}</td>
				<td class="text-right">${no_lead_time ? "" : offer.lead_time_days}</td>
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
		"Costs and rates are per stock UOM in {0}. Landed cost adds the supplier's landed cost % (or the settings default) and, for foreign currency, the FX buffer. Pricing cost spreads the supplier minimum over the customer's quantity when the customer bears it.",
		[esc(data.company_currency)]
	)}</p>`;

	dialog.fields_dict.offers_html.$wrapper.html(html);
}
