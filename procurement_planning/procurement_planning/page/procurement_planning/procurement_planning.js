// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

(() => {
	frappe.pages["procurement-planning"].on_page_load = function (wrapper) {
		const page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Procurement Planning"),
			single_column: true,
		});
		wrapper.procurement_planning = new ProcurementPlanning(page);
	};

	const API = "procurement_planning.planning.api";
	const PAGE_SIZES = [25, 50, 100];
	const ABC_CLASSES = ["A", "B", "C", "D", "E", "F", "Non-Moving"];
	const RISKS = ["High", "Medium", "Low"];
	const RISK_COLORS = { High: "red", Medium: "orange", Low: "green" };

	const FILTER_FIELDS = [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", reqd: 1 },
		{
			fieldname: "analysis_date",
			label: __("Analysis Date"),
			fieldtype: "Date",
			description: __("Sales history ends at the month before this date."),
		},
		{ fieldname: "item_group", label: __("Item Group"), fieldtype: "Link", options: "Item Group" },
		{ fieldname: "analysis_months", label: __("Analysis Months"), fieldtype: "Int", default: 12 },
		{ fieldname: "safety_stock_days", label: __("Safety Stock Days"), fieldtype: "Int", default: 45 },
		{ fieldname: "review_period_days", label: __("Review Period Days"), fieldtype: "Int", default: 30 },
		{ fieldname: "use_approved", label: __("Use Approved Parameters"), fieldtype: "Check", default: 1 },
	];

	const VARIANCE_REASONS = [
		"",
		"Budget Constraint",
		"Supplier Availability",
		"Minimum Order Qty",
		"Order Multiple",
		"Supplier Commitment",
		"Opportunity Buy",
		"Planner Judgement",
		"Other",
	];

	const COLUMNS = [
		{ fieldname: "select", label: "" },
		{ fieldname: "item_code", label: __("Item"), sortable: true },
		{ fieldname: "abc_class", label: __("ABC"), sortable: true },
		{ fieldname: "supplier", label: __("Supplier"), sortable: true },
		{ fieldname: "current_stock", label: __("Current Stock"), numeric: true, sortable: true },
		{ fieldname: "ams", label: __("Avg Monthly Sales"), numeric: true, sortable: true },
		{ fieldname: "proposed_reorder", label: __("Reorder Level"), numeric: true, sortable: true },
		{ fieldname: "target_stock", label: __("Target Stock"), numeric: true, sortable: true },
		{ fieldname: "suggested_purchase", label: __("Suggested Purchase"), numeric: true, sortable: true },
		{ fieldname: "suggested_value", label: __("Suggested Value"), numeric: true, sortable: true },
		{ fieldname: "stockout_risk", label: __("Stockout Risk"), sortable: true },
		{ fieldname: "action", label: "" },
	];

	// Dashboard cards; each card (except the total) filters the table.
	const CARDS = [
		{ key: "all", label: __("Total Items"), value: (s) => s.total_items },
		{ key: "below_reorder", label: __("Below Reorder Level"), value: (s) => s.below_reorder_level, color: "orange" },
		{ key: "requires_purchase", label: __("Requiring Purchase"), value: (s) => s.requiring_purchase, color: "blue" },
		{ key: "requires_purchase", label: __("Total Suggested Qty"), value: (s) => s.total_suggested_purchase, color: "blue", aggregate: true },
		{ key: "requires_purchase", label: __("Suggested Value"), value: (s) => s.total_suggested_value, color: "blue", aggregate: true, currency: true },
		{ key: "missing_data", label: __("Missing Planning Data"), value: (s) => s.missing_planning_data, color: "gray" },
	];

	const RISK_ORDER = { High: 0, Medium: 1, Low: 2 };

	class ProcurementPlanning {
		constructor(page) {
			this.page = page;
			this.data = null;
			this.rows = [];
			this.visible_rows = [];
			this.sort = { fieldname: "suggested_purchase", ascending: false };
			this.page_no = 0;
			this.page_size = PAGE_SIZES[0];
			this.state = { search: "", card: "all", abc_class: "", risk: "", supplier: "", requires_purchase: false, missing_lead_time: false };
			this.selected = new Set();

			this.page.set_primary_action(__("Run Analysis"), () => this.run(), "refresh");
			this.make_layout();
			this.make_filters();
			this.bind_events();
			this.page.add_inner_button(__("Settings"), () => this.open_settings());
			this.page.add_inner_button(__("Parameter Runs"), () => frappe.set_route("List", "Reorder Parameter Run"));
			this.page.add_inner_button(__("Lead Time Profiles"), () => frappe.set_route("List", "Lead Time Profile"));
		}

		open_settings() {
			const company = this.filters.company.get_value();
			if (!company) {
				frappe.set_route("List", "Procurement Planning Settings");
				return;
			}
			frappe.db.exists("Procurement Planning Settings", company).then((exists) => {
				if (exists) {
					frappe.set_route("Form", "Procurement Planning Settings", company);
				} else {
					frappe.new_doc("Procurement Planning Settings", { company });
				}
			});
		}

		make_layout() {
			this.$body = $(`
				<div class="pp-page">
					<div class="pp-panel pp-filter-panel">
						<div class="pp-filter-grid"></div>
						<div class="pp-filter-actions">
							<button class="btn btn-primary btn-sm pp-run">${__("Run Analysis")}</button>
						</div>
					</div>
					<div class="pp-empty">
						<div class="pp-empty-title">${__("Procurement planning")}</div>
						<div class="text-muted">${__(
							"Choose a company and click Run Analysis. The analysis is read-only; purchasing documents are only created when you select items and click Create Material Request."
						)}</div>
					</div>
					<div class="pp-result hide">
						<div class="pp-context">
							<span class="pp-period text-muted"></span>
							<details class="pp-notes">
								<summary>${__("Assumptions and unavailable SAP values")}</summary>
								<ul></ul>
							</details>
						</div>
						<div class="pp-cards"></div>
						<div class="pp-panel">
							<div class="pp-toolbar">
								<input type="search" class="form-control input-sm pp-search"
									placeholder="${__("Search item code or name")}">
								<select class="form-control input-sm pp-abc">
									<option value="">${__("All ABC classes")}</option>
									${ABC_CLASSES.map((c) => `<option value="${c}">${__("Class {0}", [__(c)])}</option>`).join("")}
								</select>
								<select class="form-control input-sm pp-risk">
									<option value="">${__("All risk levels")}</option>
									${RISKS.map((r) => `<option value="${r}">${__("{0} risk", [__(r)])}</option>`).join("")}
								</select>
								<select class="form-control input-sm pp-supplier">
									<option value="">${__("All suppliers")}</option>
								</select>
								<label class="pp-toggle">
									<input type="checkbox" class="pp-requires-purchase"> ${__("Purchase required")}
								</label>
								<label class="pp-toggle">
									<input type="checkbox" class="pp-missing-lead-time"> ${__("Missing lead time")}
								</label>
								<button class="btn btn-default btn-xs pp-clear">${__("Clear filters")}</button>
								<span class="pp-toolbar-spacer"></span>
								<span class="pp-selection-count text-muted"></span>
								<button class="btn btn-default btn-xs pp-select-needed">${__("Select items to buy")}</button>
								<button class="btn btn-primary btn-xs pp-create-mr" disabled>${__("Create Material Request")}</button>
							</div>
							<div class="pp-table-wrapper"><table class="pp-table"></table></div>
							<div class="pp-footer">
								<span class="pp-count text-muted"></span>
								<div class="pp-pager">
									<select class="form-control input-xs pp-page-size">
										${PAGE_SIZES.map((n) => `<option value="${n}">${__("{0} per page", [n])}</option>`).join("")}
									</select>
									<button class="btn btn-default btn-xs pp-prev">${__("Previous")}</button>
									<span class="pp-page-info text-muted"></span>
									<button class="btn btn-default btn-xs pp-next">${__("Next")}</button>
								</div>
							</div>
						</div>
					</div>
				</div>
			`).appendTo(this.page.main);
		}

		make_filters() {
			const $grid = this.$body.find(".pp-filter-grid");
			this.filters = {};
			for (const df of FILTER_FIELDS) {
				const $cell = $('<div class="pp-filter"></div>').appendTo($grid);
				const field = Object.assign({}, df);
				if (df.fieldname === "company") field.change = () => this.load_company_defaults();
				const control = frappe.ui.form.make_control({ df: field, parent: $cell, render_input: true });
				control.refresh();
				let default_value = df.default;
				if (df.fieldname === "company") default_value = frappe.defaults.get_user_default("Company");
				if (df.fieldname === "analysis_date") default_value = frappe.datetime.get_today();
				if (default_value !== undefined && default_value !== null) control.set_value(default_value);
				this.filters[df.fieldname] = control;
			}
		}

		load_company_defaults() {
			const company = this.filters.company.get_value();
			if (!company || company === this.defaults_company) return;
			this.defaults_company = company;
			frappe.call({
				method: `${API}.get_company_defaults`,
				args: { company },
				callback: (r) => {
					const d = r.message;
					if (!d) return;
					this.company_defaults = d;
					for (const fieldname of ["analysis_months", "safety_stock_days", "review_period_days"]) {
						this.filters[fieldname].set_value(d[fieldname]);
					}
				},
			});
		}

		bind_events() {
			const $b = this.$body;
			$b.find(".pp-run").on("click", () => this.run());
			$b.find(".pp-search").on(
				"input",
				frappe.utils.debounce((e) => this.update_state({ search: (e.target.value || "").trim().toLowerCase() }), 250)
			);
			$b.find(".pp-abc").on("change", (e) => this.update_state({ abc_class: e.target.value }));
			$b.find(".pp-risk").on("change", (e) => this.update_state({ risk: e.target.value }));
			$b.find(".pp-supplier").on("change", (e) => this.update_state({ supplier: e.target.value }));
			$b.find(".pp-select-needed").on("click", () => {
				for (const row of this.visible_rows) {
					if (row.suggested_purchase > 0) this.selected.add(row.item_code);
				}
				this.render_table();
			});
			$b.find(".pp-create-mr").on("click", () => this.create_material_request());
			$b.find(".pp-table").on("click", ".pp-select-row", (e) => {
				e.stopPropagation();
				const code = $(e.currentTarget).attr("data-item-code");
				if (e.currentTarget.checked) this.selected.add(code);
				else this.selected.delete(code);
				this.update_selection();
			});
			$b.find(".pp-table").on("click", ".pp-select-page", (e) => {
				e.stopPropagation();
				const checked = e.currentTarget.checked;
				for (const code of this.page_item_codes || []) {
					if (checked) this.selected.add(code);
					else this.selected.delete(code);
				}
				this.render_table();
			});
			$b.find(".pp-requires-purchase").on("change", (e) => this.update_state({ requires_purchase: e.target.checked }));
			$b.find(".pp-missing-lead-time").on("change", (e) => this.update_state({ missing_lead_time: e.target.checked }));
			$b.find(".pp-clear").on("click", () => this.clear_filters());
			$b.find(".pp-page-size").on("change", (e) => {
				this.page_size = cint(e.target.value) || PAGE_SIZES[0];
				this.go_to_page(0);
			});
			$b.find(".pp-prev").on("click", () => this.go_to_page(this.page_no - 1));
			$b.find(".pp-next").on("click", () => this.go_to_page(this.page_no + 1));
			$b.find(".pp-cards").on("click", ".pp-card", (e) => {
				const key = $(e.currentTarget).attr("data-card");
				this.update_state({ card: this.state.card === key ? "all" : key });
			});
			$b.find(".pp-table").on("click", ".pp-sort-btn", (e) => {
				const fieldname = $(e.currentTarget).attr("data-sort");
				const ascending = this.sort.fieldname === fieldname ? !this.sort.ascending : fieldname === "item_code";
				this.sort = { fieldname, ascending };
				this.refresh_table();
			});
			$b.find(".pp-table").on("click", ".pp-view", (e) => {
				e.stopPropagation();
				this.show_analysis($(e.currentTarget).attr("data-item-code"));
			});
			$b.find(".pp-table").on("click", "tbody tr[data-item-code]", (e) => {
				if ($(e.target).closest(".pp-select-cell").length) return;
				this.show_analysis($(e.currentTarget).attr("data-item-code"));
			});
		}

		get_filter_values() {
			const values = {};
			for (const [fieldname, control] of Object.entries(this.filters)) {
				values[fieldname] = control.get_value();
			}
			return values;
		}

		run() {
			const filters = this.get_filter_values();
			if (!filters.company) {
				frappe.msgprint(__("Company is required"));
				return;
			}

			frappe.call({
				method: `${API}.get_planning_analysis`,
				args: filters,
				freeze: true,
				freeze_message: __("Analysing items. This can take about half a minute..."),
				callback: (r) => {
					if (!r.message) return;
					this.filters_used = filters;
					this.data = r.message;
					this.rows = r.message.rows;
					this.missing_data = new Set(r.message.missing_data_warnings || []);
					this.selected = new Set();
					this.render_supplier_options();
					this.render_result();
				},
			});
		}

		render_supplier_options() {
			const suppliers = [...new Set(this.rows.map((row) => row.supplier).filter(Boolean))].sort();
			const has_missing = this.rows.some((row) => !row.supplier);
			this.$body.find(".pp-supplier").html(
				`<option value="">${__("All suppliers")}</option>` +
					(has_missing ? `<option value="__none__">${__("No supplier")}</option>` : "") +
					suppliers
						.map((s) => `<option value="${frappe.utils.escape_html(s)}">${frappe.utils.escape_html(s)}</option>`)
						.join("")
			);
		}

		render_result() {
			const { settings } = this.data;
			this.$body.find(".pp-empty").addClass("hide");
			this.$body.find(".pp-result").removeClass("hide");

			this.$body.find(".pp-period").text(
				__("{0} · As of {8} · Analysis {1} – {2} ({3} months) · ABC period {4} – {5} · Safety {6} days · Review {7} days", [
					settings.company,
					frappe.datetime.str_to_user(settings.analysis_from),
					frappe.datetime.str_to_user(settings.analysis_to),
					settings.analysis_months,
					frappe.datetime.str_to_user(settings.abc_from),
					frappe.datetime.str_to_user(settings.abc_to),
					settings.safety_stock_days,
					settings.review_period_days,
					frappe.datetime.str_to_user(settings.analysis_date),
				])
			);
			this.$body
				.find(".pp-notes ul")
				.html(this.data.notes.map((note) => `<li>${frappe.utils.escape_html(note)}</li>`).join(""));

			this.clear_filters();
		}

		render_cards() {
			const summary = this.data.summary;
			this.$body.find(".pp-cards").html(
				CARDS.map((card) => {
					const active = this.state.card === card.key;
					return `
						<button type="button" class="pp-card ${active ? "active" : ""} ${card.color ? `pp-card-${card.color}` : ""}"
							data-card="${card.key}" aria-pressed="${active}"
							title="${card.key === "all" ? __("Show all items") : __("Filter the table")}">
							<div class="pp-card-label">${card.label}</div>
							<div class="pp-card-value">${
								card.currency ? format_money(card.value(summary), this.data.settings.currency) : format_qty(card.value(summary))
							}</div>
						</button>`;
				}).join("")
			);
		}

		update_state(changes) {
			Object.assign(this.state, changes);
			this.page_no = 0;
			this.refresh_table();
		}

		clear_filters() {
			this.state = { search: "", card: "all", abc_class: "", risk: "", supplier: "", requires_purchase: false, missing_lead_time: false };
			const $b = this.$body;
			$b.find(".pp-search").val("");
			$b.find(".pp-abc, .pp-risk, .pp-supplier").val("");
			$b.find(".pp-requires-purchase, .pp-missing-lead-time").prop("checked", false);
			this.page_no = 0;
			this.refresh_table();
		}

		matches(row) {
			const s = this.state;
			if (s.search && !`${row.item_code} ${row.item_name || ""} ${row.supplier || ""}`.toLowerCase().includes(s.search)) return false;
			if (s.abc_class && row.abc_class !== s.abc_class) return false;
			if (s.risk && row.stockout_risk !== s.risk) return false;
			if (s.supplier === "__none__" && row.supplier) return false;
			if (s.supplier && s.supplier !== "__none__" && row.supplier !== s.supplier) return false;
			if (s.requires_purchase && !(row.suggested_purchase > 0)) return false;
			if (s.missing_lead_time && !row.warnings.some((w) => w === "LEAD_TIME_FALLBACK" || w === "LEAD_TIME_DEFAULT")) return false;
			if (s.card === "below_reorder" && !row.below_reorder_level) return false;
			if (s.card === "requires_purchase" && !(row.suggested_purchase > 0)) return false;
			if (s.card === "missing_data" && !row.warnings.some((w) => this.missing_data.has(w))) return false;
			return true;
		}

		refresh_table() {
			if (!this.data) return;
			const { fieldname, ascending } = this.sort;
			const direction = ascending ? 1 : -1;
			const sort_value = (row) => {
				if (fieldname === "stockout_risk") return RISK_ORDER[row.stockout_risk];
				if (fieldname === "abc_class") return ABC_CLASSES.indexOf(row.abc_class);
				return row[fieldname];
			};

			this.visible_rows = this.rows.filter((row) => this.matches(row)).sort((a, b) => {
				const x = sort_value(a);
				const y = sort_value(b);
				if (x === y) return 0;
				if (x === null || x === undefined) return 1;
				if (y === null || y === undefined) return -1;
				return (typeof x === "number" ? x - y : String(x).localeCompare(String(y))) * direction;
			});

			this.render_cards();
			this.render_table();
		}

		go_to_page(page_no) {
			const last_page = Math.max(0, Math.ceil(this.visible_rows.length / this.page_size) - 1);
			this.page_no = Math.min(Math.max(page_no, 0), last_page);
			this.render_table();
		}

		render_table() {
			const total = this.visible_rows.length;
			const pages = Math.max(1, Math.ceil(total / this.page_size));
			const start = this.page_no * this.page_size;
			const page_rows = this.visible_rows.slice(start, start + this.page_size);

			this.page_item_codes = page_rows.map((row) => row.item_code);
			const all_selected = page_rows.length > 0 && page_rows.every((row) => this.selected.has(row.item_code));
			const header = COLUMNS.map((column) => {
				if (column.fieldname === "select") {
					return `<th class="pp-select-cell"><input type="checkbox" class="pp-select-page" title="${__("Select this page")}" ${
						all_selected ? "checked" : ""
					}></th>`;
				}
				const classes = [column.numeric ? "pp-num" : "", column.sortable ? "pp-sortable" : ""].join(" ");
				const sorted = this.sort.fieldname === column.fieldname;
				const arrow = sorted ? `<span class="pp-sort">${this.sort.ascending ? "▲" : "▼"}</span>` : "";
				const label = column.sortable
					? `<button type="button" class="pp-sort-btn" data-sort="${column.fieldname}">${column.label}${arrow}</button>`
					: column.label;
				return `<th class="${classes}">${label}</th>`;
			}).join("");

			const body = page_rows.map((row) => this.table_row(row)).join("");
			const empty = `<tr><td colspan="${COLUMNS.length}" class="pp-no-rows">${__("No items match the filters")}</td></tr>`;

			this.$body.find(".pp-table").html(`<thead><tr>${header}</tr></thead><tbody>${body || empty}</tbody>`);
			this.$body.find(".pp-count").text(
				total === this.rows.length
					? __("{0} items", [format_number(total, null, 0)])
					: __("{0} of {1} items", [format_number(total, null, 0), format_number(this.rows.length, null, 0)])
			);
			this.$body.find(".pp-page-info").text(__("Page {0} of {1}", [this.page_no + 1, pages]));
			this.$body.find(".pp-prev").prop("disabled", this.page_no === 0);
			this.$body.find(".pp-next").prop("disabled", this.page_no + 1 >= pages);
			this.$body.find(".pp-page-size").val(String(this.page_size));
			this.update_selection();
		}

		update_selection() {
			const count = this.selected.size;
			this.$body.find(".pp-selection-count").text(count ? __("{0} selected", [count]) : "");
			this.$body.find(".pp-create-mr").prop("disabled", !count);
		}

		create_material_request() {
			const rows = this.rows.filter((row) => this.selected.has(row.item_code));
			if (!rows.length) return;
			new MaterialRequestDialog(this, rows).show();
		}

		table_row(row) {
			const code = frappe.utils.escape_html(row.item_code);
			const name = frappe.utils.escape_html(row.item_name || "");
			const lead_time_missing = row.warnings.includes("LEAD_TIME_FALLBACK");
			const lead_time_default = row.warnings.includes("LEAD_TIME_DEFAULT");
			const shown = (lead_time_missing ? 1 : 0) + (lead_time_default ? 1 : 0);
			const other_warnings = row.warnings.length - shown;
			const supplier = row.supplier ? frappe.utils.escape_html(row.supplier) : "";
			const supplier_note =
				row.supplier_source === "Last PO"
					? `<div class="pp-item-name">${__("from PO history")}</div>`
					: row.blanket_order
					? `<div class="pp-item-name">${frappe.utils.escape_html(row.blanket_order)} · ${__("{0} left", [format_qty(row.blanket_order_remaining)])}</div>`
					: "";
			const warning_title = frappe.utils.escape_html(
				row.warnings.map((w) => this.data.warning_labels[w] || w).join("\n")
			);

			return `
				<tr data-item-code="${code}" class="pp-risk-row-${(row.stockout_risk || "").toLowerCase()} ${
					this.selected.has(row.item_code) ? "pp-selected" : ""
				}">
					<td class="pp-select-cell"><input type="checkbox" class="pp-select-row" data-item-code="${code}" ${
						this.selected.has(row.item_code) ? "checked" : ""
					}></td>
					<td class="pp-item">
						<div class="pp-item-code">${code}</div>
						<div class="pp-item-name" title="${name}">${name}</div>
					</td>
					<td>${abc_pill(row.abc_class)}</td>
					<td class="pp-supplier-cell">${supplier ? `<div title="${supplier}">${supplier}</div>${supplier_note}` : `<span class="text-muted">—</span>`}</td>
					<td class="pp-num">${format_qty(row.current_stock)}</td>
					<td class="pp-num">${format_qty(row.ams)}</td>
					<td class="pp-num">${format_qty(row.proposed_reorder)}</td>
					<td class="pp-num">${format_qty(row.target_stock)}</td>
					<td class="pp-num">${suggested_badge(row.suggested_purchase)}</td>
					<td class="pp-num">${row.suggested_purchase > 0 ? format_money(row.suggested_value, this.data.settings.currency) : `<span class="text-muted">—</span>`}</td>
					<td>
						${risk_pill(row.stockout_risk)}
						${lead_time_missing ? `<span class="pp-flag" title="${warning_title}">${__("No lead time")}</span>` : ""}
						${lead_time_default ? `<span class="pp-flag" title="${warning_title}">${__("Default lead time")}</span>` : ""}
						${row.parameter_source === "Approved" ? `<span class="pp-flag pp-flag-approved" title="${__("Approved parameters")}">${__("Approved")}</span>` : ""}
						${other_warnings > 0 ? `<span class="pp-flag" title="${warning_title}">+${other_warnings}</span>` : ""}
					</td>
					<td class="pp-action">
						<button class="btn btn-default btn-xs pp-view" data-item-code="${code}">${__("View Analysis")}</button>
					</td>
				</tr>`;
		}

		show_analysis(item_code) {
			frappe.call({
				method: `${API}.get_item_planning_details`,
				args: Object.assign({}, this.filters_used, { item_code }),
				freeze: true,
				freeze_message: __("Loading analysis..."),
				callback: (r) => r.message && new ItemAnalysisDialog(r.message).show(),
			});
		}
	}

	class ItemAnalysisDialog {
		constructor(data) {
			this.data = data;
			this.item = data.item;
			this.settings = data.settings;
		}

		show() {
			const item = this.item;
			const dialog = new frappe.ui.Dialog({
				// Dialog renders its title as HTML.
				title: frappe.utils.escape_html(`${item.item_code}: ${item.item_name}`),
				size: "extra-large",
				fields: [{ fieldtype: "HTML", fieldname: "analysis" }],
			});
			dialog.fields_dict.analysis.$wrapper.html(`
				<div class="pp-analysis">
					${this.headline()}
					${this.section(__("Inventory and Demand"), this.inventory_summary())}
					${this.section(__("SAP vs Proposed"), this.comparison())}
					<div class="pp-two-columns">
						${this.section(__("SAP Calculation (original method)"), this.sap_breakdown(), "pp-sap")}
						${this.section(__("Proposed Calculation"), this.proposed_breakdown(), "pp-proposed")}
					</div>
					<div class="pp-two-columns">
						${this.section(__("Monthly Sales History"), this.monthly_history())}
						${this.section(__("Planning Warnings"), this.warnings())}
					</div>
				</div>
			`);
			dialog.show();
		}

		section(title, content, css_class = "") {
			return `<div class="pp-section ${css_class}"><div class="pp-section-title">${title}</div>${content}</div>`;
		}

		headline() {
			const item = this.item;
			const p = item.proposed;
			return `
				<div class="pp-headline">
					<div class="pp-headline-tags">
						${abc_pill(item.abc_class)}
						${risk_pill(p.stockout_risk)}
						${p.lead_time_is_fallback ? `<span class="indicator-pill gray">${__("No lead time")}</span>` : ""}
						${p.parameter_source === "Approved" ? `<span class="indicator-pill green">${__("Approved parameters · {0}", [frappe.utils.escape_html(item.approved_run || "")])}</span>` : ""}
						<span class="text-muted">${frappe.utils.escape_html(item.stock_uom || "")}${
							item.sap_code ? ` · ${__("SAP Code")} ${frappe.utils.escape_html(item.sap_code)}` : ""
						}</span>
					</div>
					<div class="pp-headline-purchase ${p.suggested_purchase > 0 ? "pp-needs-purchase" : ""}">
						<div class="pp-headline-label">${__("Suggested Purchase")}</div>
						<div class="pp-headline-value">${format_qty(p.suggested_purchase)}</div>
						${p.moq_adjustment ? `<div class="pp-headline-note">${__("incl. MOQ adjustment {0}", [format_qty(p.moq_adjustment)])}</div>` : ""}
						${p.multiple_adjustment ? `<div class="pp-headline-note">${__("incl. order multiple adjustment {0}", [format_qty(p.multiple_adjustment)])}</div>` : ""}
						${p.suggested_purchase > 0 && item.last_purchase_rate ? `<div class="pp-headline-note">${__("≈ {0} at last purchase rate", [format_money(item.suggested_value, this.settings.currency)])}</div>` : ""}
					</div>
				</div>`;
		}

		inventory_summary() {
			const item = this.item;
			const po = item.po_buckets;
			return `<div class="pp-stats">
				${stat(__("Current Stock"), item.current_stock, __("Reservation {0} · Transit {1}", [format_qty(item.reservation_stock), format_qty(item.transit_stock)]))}
				${stat(__("Open Sales Orders"), item.open_so, __("Due in horizon {0} · Later {1}", [item.open_so_due, item.open_so_future].map(format_qty)))}
				${stat(__("Open Purchase Orders"), item.open_po, __("In transit {0} · Due {1} · Late {2} · Overdue {3} · Later {4} · Undated {5}", [po.in_transit + po.in_transit_late, po.due, po.late, po.overdue, po.beyond, po.undated].map(format_qty)))}
				${item.back_to_back_so || item.back_to_back_po ? stat(__("Back-to-Back (excluded)"), null, __("SO {0} · PO {1}", [format_qty(item.back_to_back_so), format_qty(item.back_to_back_po)]), true) : ""}
				${stat(__("Next Expected PO"), null, format_date(item.next_expected_po_date), true)}
				${stat(__("Pending Purchase MR"), item.pending_pr, __("Not PR Foreign; subtracted from the suggestion"))}
				${stat(__("Net Sales (months used)"), item.net_sales, __("{0} months used of {1} · {2} stock-out months left out", [item.eligible_months, this.settings.analysis_months, (item.stockout_months || []).length]))}
				${stat(__("Net Sales (fixed 12 months)"), item.net_sales_12m, __("{0} months with sales", [item.months_with_sales]))}
				${stat(__("Supplier"), null, item.supplier ? `${item.supplier} (${__(item.supplier_source)})` : __("Not found"), true)}
				${item.blanket_order ? stat(__("Blanket Order"), item.blanket_order_remaining, __("{0} · left to order · agreed rate {1} · valid to {2}", [item.blanket_order, agreed_rate(item, this.settings.currency), format_date(item.blanket_order_to_date)])) : ""}
				${stat(__("Lead Time"), null, item.lead_time_days ? __("{0} days · {1}", [item.lead_time_days, lead_time_label(item)]) : __("Not available"), true)}
				${stat(__("Minimum Order Qty"), item.min_order_qty, item.order_multiple ? __("Order multiple {0}", [format_qty(item.order_multiple)]) : "")}
				${stat(__("Last Purchase Rate"), null, item.last_purchase_rate ? format_money(item.last_purchase_rate, this.settings.currency) : __("Not available"), true)}
			</div>`;
		}

		sap_value(metric, { assumed = false, rate = false } = {}) {
			const sap = this.item.sap;
			if (sap[metric] === null || sap[metric] === undefined) {
				return `<span class="indicator-pill gray" title="${frappe.utils.escape_html(sap.unavailable[metric] || "")}">${__("Unavailable")}</span>
					<div class="pp-reason">${frappe.utils.escape_html(sap.unavailable[metric] || "")}</div>`;
			}
			return `${(rate ? format_operand : format_qty)(sap[metric])}${assumed ? `<div class="pp-reason">${__("Uses assumed Grace Days = Item Lead Time (unverified)")}</div>` : ""}`;
		}

		comparison() {
			const item = this.item;
			const p = item.proposed;
			const s = this.settings;
			const rows = [
				[__("Average monthly sales"), this.sap_value("avg_mon"), format_qty(p.ams), __("SAP: fixed 12 months · Proposed: analysis period, eligible months")],
				[__("Average daily sales"), this.sap_value("daily_avg"), format_qty(p.ads), __("Proposed ADS used for planning: {0}", [format_qty(p.planning_ads)])],
				[__("Safety stock"), this.sap_value("safety"), format_qty(p.safety_stock), p.parameter_source === "Approved" ? __("Proposed: approved value (calculated {0})", [format_qty(p.calculated_safety_stock)]) : __("SAP {0} days · Proposed {1} days", [s.sap_safety_days, s.safety_stock_days])],
				[__("Reorder point"), this.sap_value("reorder", { assumed: true }), format_qty(p.reorder_level), __("SAP Re-Order · Proposed Reorder Level")],
				[__("Maximum / target stock"), this.sap_value("max", { assumed: true }), format_qty(p.target_stock), __("SAP Max · Proposed Target Stock")],
				[__("Minimum"), this.sap_value("min"), "—", __("Not part of the proposed method")],
				[__("Recommended purchase"), this.sap_value("rec_qty"), `<span class="pp-strong">${format_qty(p.suggested_purchase)}</span>`, __("SAP Rec Qty · Proposed Suggested Purchase")],
			];
			return `<table class="pp-detail-table pp-compare">
				<thead><tr><th>${__("Measure")}</th><th class="pp-num">${__("SAP (original)")}</th><th class="pp-num">${__("Proposed")}</th><th>${__("Basis")}</th></tr></thead>
				<tbody>${rows
					.map(([label, sap, proposed, basis]) => `<tr><th>${label}</th><td class="pp-num">${sap}</td><td class="pp-num">${proposed}</td><td class="text-muted">${basis}</td></tr>`)
					.join("")}</tbody></table>`;
		}

		sap_breakdown() {
			const item = this.item;
			const grace = item.grace_days === null ? __("unavailable") : `${item.grace_days} (${__("assumed")})`;
			const line = (label, formula, metric, assumed = false, rate = false) => [
				label,
				formula,
				this.sap_value(metric, { assumed, rate }),
			];
			return formula_table([
				line(__("Avg/Mon"), `${format_qty(item.net_sales_12m)} / 12`, "avg_mon"),
				line(__("Avg/Cont"), `${format_qty(item.net_sales_12m)} / ${item.months_with_sales} ${__("selling months")}`, "avg_cont"),
				line(__("Daily Avg"), `${format_qty(item.net_sales_12m)} / 365`, "daily_avg", false, true),
				line(__("Re-Order"), `ceil(${__("Daily Avg")} × ${__("Grace Days")} ${grace})`, "reorder", true),
				line(__("Safety"), `ceil(${__("Daily Avg")} × ${this.settings.sap_safety_days})`, "safety"),
				line(__("Min"), __("Class-dependent rule (not confirmed)"), "min"),
				line(__("Max"), `${__("Re-Order")} + ${__("Safety")}`, "max", true),
				line(__("Miss Qty"), `${format_qty(item.current_stock)} + ${format_qty(item.open_po)} − ${format_qty(item.open_so)}`, "miss_qty"),
				line(__("To Reorder"), `${__("Stock")} + ${__("Open PO")} + ${__("PR Foreign")} − ${__("Open SO")} − ${__("Re-Order")}`, "to_reorder"),
				line(__("Rec Qty"), `max(0, ${__("Avg/Mon")} × 12 + ${__("Open SO")} − ${__("Stock")} − ${__("Open PO")} − ${__("PR Foreign")})`, "rec_qty"),
				line(__("Missing SO"), `${__("Stock")} + ${__("Open PO")} + ${__("PR Foreign")} − ${__("Open SO")}`, "missing_so"),
				line(__("To Reorder Final"), `${__("To Reorder")} − ${__("PR Foreign")}`, "to_reorder_final"),
			]);
		}

		proposed_breakdown() {
			const item = this.item;
			const p = item.proposed;
			const s = this.settings;
			const lead = __("{0} days", [p.lead_time_days]);
			const lead_source = p.lead_time_is_fallback ? __("No lead time found") : lead_time_label(item);
			const approved = p.parameter_source === "Approved";
			return formula_table([
				[__("AMS"), `${format_qty(item.net_sales)} / ${item.eligible_months} ${__("months used")}`, format_operand(p.ams)],
				[__("ADS"), `max(0, ${format_operand(p.ams)} × 12 / 365)`, format_operand(p.ads)],
				[__("ADS for planning"), item.abc_class === "Non-Moving" ? __("0 for non-moving items") : __("= ADS"), format_operand(p.planning_ads)],
				[__("Lead Time"), frappe.utils.escape_html(lead_source), lead],
				[__("Planning Horizon"), `${p.lead_time_days} + ${s.review_period_days}`, __("{0} days", [p.planning_horizon_days])],
				[__("Safety Stock"), approved ? __("Approved (calculated: ceil({0} × {1}) = {2})", [format_operand(p.planning_ads), s.safety_stock_days, format_qty(p.calculated_safety_stock)]) : `ceil(${format_operand(p.planning_ads)} × ${s.safety_stock_days})`, format_qty(p.safety_stock)],
				[__("Forecast Demand"), `ceil(${format_operand(p.planning_ads)} × ${p.planning_horizon_days})`, format_qty(p.forecast_demand)],
				[__("Target Stock"), approved ? __("Approved (calculated {0})", [format_qty(p.calculated_target_stock)]) : `${format_qty(p.forecast_demand)} + ${format_qty(p.safety_stock)}`, format_qty(p.target_stock)],
				[__("Reorder Level"), approved ? __("Approved (calculated {0})", [format_qty(p.calculated_reorder_level)]) : `ceil(${format_operand(p.planning_ads)} × ${p.lead_time_days}) + ${format_qty(p.safety_stock)}`, format_qty(p.reorder_level)],
				[__("Open SO Demand"), __("Due by {0}", [format_date(item.horizon_end)]), format_qty(p.open_so_demand)],
				[__("Required Stock"), `max(${__("Target")} ${format_qty(p.target_stock)}, ${__("Open SO")} ${format_qty(p.open_so_demand)} + ${__("Safety")} ${format_qty(p.safety_stock)})`, format_qty(p.required_stock)],
				[__("Open PO Supply"), __("Shipped, due and late (up to {0} days) by {1}", [s.late_po_tolerance_days, format_date(item.horizon_end)]), format_qty(p.open_po_supply)],
				[__("Inventory Position"), `${format_qty(item.current_stock)} + ${format_qty(p.open_po_supply)}`, format_qty(p.inventory_position)],
				[__("Purchase Need"), `${format_qty(p.required_stock)} − ${format_qty(p.inventory_position)}`, format_qty(p.purchase_need)],
				[__("MOQ Adjustment"), __("Item Minimum Order Qty {0}", [format_qty(item.min_order_qty)]), format_qty(p.moq_adjustment)],
				[__("Order Multiple"), __("Round up to {0}", [format_qty(item.order_multiple)]), format_qty(p.multiple_adjustment)],
				[__("Suggested Purchase"), `max(0, ceil(${format_qty(p.purchase_need)} − ${format_qty(p.pending_requests || 0)} ${__("pending MR")})) + ${format_qty(p.moq_adjustment)} + ${format_qty(p.multiple_adjustment)}`, `<span class="pp-strong">${format_qty(p.suggested_purchase)}</span>`],
				[__("Stockout Risk"), __("High: Open SO > Stock or Position < Required − Safety; Medium: Position < Required"), risk_pill(p.stockout_risk)],
			]);
		}

		monthly_history() {
			const history = this.item.monthly_history;
			const peak = Math.max(1, ...history.map((m) => Math.abs(m.net_sales)));
			const rows = history
				.map((m) => {
					const width = Math.round((Math.abs(m.net_sales) / peak) * 100);
					return `<tr>
						<td>${m.month}</td>
						<td class="pp-bar-cell"><div class="pp-bar ${m.net_sales < 0 ? "pp-bar-negative" : ""}" style="width: ${width}%"></div></td>
						<td class="pp-num">${format_qty(m.net_sales)}</td>
						<td class="pp-period-flags">${m.used ? `<span class="indicator-pill blue">${__("Used")}</span>` : ""}${
						m.stockout ? `<span class="indicator-pill orange" title="${__("Out of stock {0} of {1} days", [m.stockout_days, m.days])}">${__("Stock-out")}</span>` : ""
					}${!m.stockout && m.stockout_days ? `<span class="text-muted pp-stockout-days">${__("{0}d out", [m.stockout_days])}</span>` : ""}${
						m.in_abc ? `<span class="indicator-pill gray">${__("ABC")}</span>` : ""
					}</td>
					</tr>`;
				})
				.join("");
			return `<table class="pp-detail-table pp-history"><tbody>${rows}</tbody></table>`;
		}

		warnings() {
			const labels = this.data.warning_labels;
			const warnings = this.item.proposed.warnings;
			if (!warnings.length) return `<div class="text-muted">${__("No warnings")}</div>`;
			return `<ul class="pp-warnings">${warnings
				.map((code) => `<li>${frappe.utils.escape_html(labels[code] || code)}</li>`)
				.join("")}</ul>`;
		}
	}

	class MaterialRequestDialog {
		constructor(planner, rows) {
			this.planner = planner;
			this.rows = rows;
			this.settings = planner.data.settings;
		}

		show() {
			const base = frappe.datetime.str_to_obj(frappe.datetime.get_today());
			const data = this.rows.map((row) => {
				const date = new Date(base);
				date.setDate(date.getDate() + (row.lead_time_days || 0));
				return {
					item_code: row.item_code,
					supplier: row.supplier || "",
					suggested_qty: row.suggested_purchase,
					qty: row.suggested_purchase,
					uom: row.stock_uom,
					variance_reason: "",
					schedule_date: frappe.datetime.obj_to_str(date),
				};
			});

			const dialog = new frappe.ui.Dialog({
				title: __("Create Material Request"),
				size: "extra-large",
				fields: [
					{
						fieldtype: "HTML",
						options: `<p class="text-muted">${__(
							"A draft Purchase Material Request is created. Change a quantity only with a variance reason; quantities are in stock UOM."
						)}</p>`,
					},
					{
						fieldname: "warehouse",
						fieldtype: "Link",
						label: __("Target Warehouse"),
						options: "Warehouse",
						reqd: 1,
						default: this.settings.default_purchase_warehouse,
						get_query: () => ({ filters: { company: this.settings.company, is_group: 0 } }),
					},
					{
						fieldname: "items",
						fieldtype: "Table",
						label: __("Items"),
						cannot_add_rows: true,
						in_place_edit: true,
						data,
						fields: [
							{ fieldname: "item_code", fieldtype: "Link", options: "Item", label: __("Item"), in_list_view: 1, read_only: 1, columns: 2 },
							{ fieldname: "supplier", fieldtype: "Link", options: "Supplier", label: __("Supplier"), in_list_view: 1, columns: 2 },
							{ fieldname: "suggested_qty", fieldtype: "Float", label: __("Suggested"), in_list_view: 1, read_only: 1, columns: 1 },
							{ fieldname: "qty", fieldtype: "Float", label: __("Qty"), in_list_view: 1, reqd: 1, columns: 1 },
							{ fieldname: "variance_reason", fieldtype: "Select", options: VARIANCE_REASONS.join("\n"), label: __("Variance Reason"), in_list_view: 1, columns: 2 },
							{ fieldname: "schedule_date", fieldtype: "Date", label: __("Required By"), in_list_view: 1, columns: 2 },
							{ fieldname: "uom", fieldtype: "Data", label: __("UOM"), read_only: 1 },
						],
					},
				],
				primary_action_label: __("Create Draft"),
				primary_action: (values) => this.submit(dialog, values),
			});
			dialog.show();
		}

		submit(dialog, values) {
			const items = (values.items || []).filter((row) => flt(row.qty) > 0);
			if (!items.length) {
				frappe.msgprint(__("Enter a quantity above zero for at least one item"));
				return;
			}
			const missing = items.filter((row) => Math.abs(flt(row.qty) - flt(row.suggested_qty)) > 1e-9 && !row.variance_reason);
			if (missing.length) {
				frappe.msgprint(
					__("Select a Variance Reason for: {0}", [missing.map((row) => frappe.utils.escape_html(row.item_code)).join(", ")])
				);
				return;
			}

			frappe.call({
				method: `${API}.create_material_request`,
				args: { company: this.settings.company, warehouse: values.warehouse, items },
				freeze: true,
				freeze_message: __("Creating Material Request..."),
				callback: (r) => {
					if (!r.message) return;
					dialog.hide();
					this.planner.selected = new Set();
					this.planner.render_table();
					frappe.msgprint({
						title: __("Material Request Created"),
						indicator: "green",
						message: __("Draft {0} created with {1} items.", [
							frappe.utils.get_form_link("Material Request", r.message, true),
							items.length,
						]),
					});
				},
			});
		}
	}

	function format_qty(value) {
		if (value === null || value === undefined) return "—";
		return format_number(value, null, Number.isInteger(value) ? 0 : 2);
	}

	// Formula operands such as daily rates need more decimals than displayed results.
	function format_operand(value) {
		if (value === null || value === undefined) return "—";
		return format_number(value, null, Number.isInteger(value) ? 0 : 4);
	}

	function format_money(value, currency) {
		if (value === null || value === undefined) return "—";
		return format_currency(value, currency, 0);
	}

	// Agreed rate in the agreement's (supplier's) currency, with the company currency value: "$140 (525 SAR)".
	function agreed_rate(item, company_currency) {
		const currency = item.blanket_order_currency || company_currency;
		const agreed = format_currency(item.blanket_order_rate, currency, 2);
		if (currency === company_currency) return agreed;
		const base = item.blanket_order_base_rate
			? format_currency(item.blanket_order_base_rate, company_currency, 2)
			: __("no exchange rate");
		return `${agreed} (${base})`;
	}

	function lead_time_label(item) {
		const source = item.lead_time_source;
		if (source === "Profile") return __("Lead Time Profile {0}", [frappe.utils.escape_html(item.lead_time_profile || "")]);
		if (source === "Item") return __("Item");
		if (source === "Default") return __("company default");
		if (source === "Approved Run") return __("approved run");
		return __(source || "none");
	}

	function format_date(value) {
		return value ? frappe.datetime.str_to_user(value) : "—";
	}

	function abc_pill(abc_class) {
		const color = abc_class === "Non-Moving" ? "gray" : ["A", "B"].includes(abc_class) ? "blue" : "purple";
		return `<span class="indicator-pill ${color} pp-abc-pill">${frappe.utils.escape_html(__(abc_class || ""))}</span>`;
	}

	function risk_pill(risk) {
		return `<span class="indicator-pill ${RISK_COLORS[risk] || "gray"}">${frappe.utils.escape_html(__(risk || ""))}</span>`;
	}

	function suggested_badge(qty) {
		return qty > 0 ? `<span class="pp-suggested">${format_qty(qty)}</span>` : `<span class="text-muted">0</span>`;
	}

	function stat(label, value, note = "", text_value = false) {
		return `<div class="pp-stat">
			<div class="pp-stat-label">${label}</div>
			<div class="pp-stat-value ${text_value ? "pp-stat-text" : ""}">${text_value ? frappe.utils.escape_html(String(note)) : format_qty(value)}</div>
			${!text_value && note ? `<div class="pp-stat-note">${frappe.utils.escape_html(note)}</div>` : ""}
		</div>`;
	}

	function formula_table(rows) {
		return `<div class="pp-precision-note">${__("Results are calculated at full precision; operands are shown rounded.")}</div>
		<table class="pp-detail-table pp-formulas">
			<thead><tr><th>${__("Metric")}</th><th>${__("Calculation")}</th><th class="pp-num">${__("Value")}</th></tr></thead>
			<tbody>${rows
				.map(([label, formula, value]) => `<tr><th>${label}</th><td class="pp-formula">${formula}</td><td class="pp-num">${value}</td></tr>`)
				.join("")}</tbody></table>`;
	}
})();
