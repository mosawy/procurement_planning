// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.pages["planned-purchasing-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Planned Purchasing Dashboard"),
		single_column: true,
	});
	wrapper.dashboard = new PlannedPurchasingDashboard(page);
};

class PlannedPurchasingDashboard {
	constructor(page) {
		this.page = page;
		this.d = procurement_planning.dashboard;
		this.company = page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			change: () => this.load(),
		});
		this.analysis_date = page.add_field({
			fieldname: "analysis_date",
			label: __("As of"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			change: () => this.load(),
		});
		page.set_primary_action(__("Refresh"), () => this.load(true), "refresh");
		page.add_inner_button(__("Planning Screen"), () => this.open_planning({}));
		page.add_inner_button(__("Parameter Runs"), () => frappe.set_route("List", "Reorder Parameter Run"));

		this.$body = $('<div class="pd-page"></div>').appendTo(page.body);
		this.load();
	}

	load(refresh = false) {
		const company = this.company.get_value();
		if (!company) {
			this.$body.html(this.d.empty(__("Choose a company"), __("The dashboard shows where planned purchasing stands for one company."), "🏢"));
			return;
		}
		const args = { company, analysis_date: this.analysis_date.get_value(), refresh: refresh ? 1 : 0 };
		const key = JSON.stringify([args.company, args.analysis_date]);
		// Field defaults fire change events: do not load the same view twice.
		if (!refresh && key === this.loaded_key) return;
		this.loaded_key = key;
		this.$body.html(this.d.loading());
		frappe
			.call({
				method: "procurement_planning.planning.dashboard_data.get_planned_dashboard",
				args,
				freeze: refresh,
				freeze_message: __("Analysing items. This can take about half a minute..."),
			})
			.then((r) => {
				this.data = r.message;
				this.render();
			});
	}

	open_planning(options) {
		frappe.route_options = Object.assign(
			{ company: this.company.get_value(), analysis_date: this.analysis_date.get_value() },
			options
		);
		frappe.set_route("procurement-planning");
	}

	render() {
		const data = this.data;
		const d = this.d;
		this.$body.html(`
			<div class="pd-meta">
				<span>${__("{0} · as of {1}", [d.esc(data.company), d.date(data.analysis_date)])}</span>
				<span>${__("Calculated {0} · cached 10 minutes, Refresh recalculates", [frappe.datetime.comment_when(data.generated_at)])}</span>
			</div>
			<div class="pd-grid pd-grid-kpi pd-kpis"></div>
			<div class="pd-grid pd-grid-3">
				<div class="pd-run"></div>
				<div class="pd-agreements" style="grid-column: span 1"></div>
				<div class="pd-alerts"></div>
			</div>
			<div class="pd-grid pd-grid-3">
				<div class="pd-panel"><div class="pd-panel-title">${__("Suggested purchase by supplier")}<span class="pd-hint">${__("Top 10 · click a bar")}</span></div><div class="pd-chart-supplier"></div></div>
				<div class="pd-panel"><div class="pd-panel-title">${__("Stock-out risk by ABC class")}<span class="pd-hint">${__("Items")}</span></div><div class="pd-chart-risk"></div></div>
				<div class="pd-panel"><div class="pd-panel-title">${__("Purchase Orders vs agreement plan, {0}", [data.charts.plan_vs_actual.year])}</div><div class="pd-chart-plan"></div></div>
			</div>
			<div class="pd-top-items"></div>
		`);
		this.render_kpis();
		this.render_run();
		this.render_agreements();
		this.render_alerts();
		this.render_charts();
		this.render_top_items();
	}

	render_kpis() {
		const { kpis, currency } = this.data;
		const d = this.d;
		const transit = kpis.in_transit;
		const cards = [
			{
				key: "below_reorder",
				label: __("Below reorder level"),
				value: d.number(kpis.below_reorder),
				sub: __("of {0} items", [d.number(kpis.total_items)]),
				accent: kpis.below_reorder ? "orange" : "green",
				open: () => this.open_planning({ card: "below_reorder" }),
			},
			{
				key: "high_risk",
				label: __("High stock-out risk"),
				value: d.number(kpis.high_risk),
				sub: __("items at risk before supply arrives"),
				accent: kpis.high_risk ? "red" : "green",
				open: () => this.open_planning({ risk: "High" }),
			},
			{
				key: "suggested",
				label: __("Suggested purchase"),
				value: d.compact(kpis.suggested_value, currency),
				sub: __("{0} items to buy", [d.number(kpis.items_to_buy)]),
				title: d.money(kpis.suggested_value, currency),
				accent: "blue",
				open: () => this.open_planning({ card: "requires_purchase" }),
			},
			{
				key: "missing",
				label: __("Missing planning data"),
				value: d.number(kpis.no_supplier + kpis.no_lead_time),
				sub: `<a data-sub="no_supplier">${__("{0} no supplier", [kpis.no_supplier])}</a> · <a data-sub="no_lead_time">${__("{0} no lead time", [kpis.no_lead_time])}</a>`,
				accent: kpis.no_supplier + kpis.no_lead_time ? "purple" : "green",
				open: () => this.open_planning({ card: "missing_data" }),
			},
			{
				key: "late_pos",
				label: __("Late Purchase Orders"),
				value: d.number(kpis.late_pos.count),
				sub: __("{0} to receive · {1} days tolerance", [d.compact(kpis.late_pos.value, currency), kpis.late_pos.tolerance_days]),
				accent: kpis.late_pos.count ? "red" : "green",
				open: () => d.open_list("Purchase Order", kpis.late_pos.names),
			},
			transit
				? {
						key: "transit",
						label: __("In transit"),
						value: d.compact(transit.value, currency),
						sub: __("{0} units shipped, not received", [d.number(transit.qty)]),
						accent: "blue",
						open: () => d.open_list("Purchase Order", transit.names),
				  }
				: {
						key: "transit",
						label: __("In transit"),
						value: "—",
						sub: __("Shipment tracking not installed"),
						accent: "gray",
						clickable: false,
				  },
		];
		const $kpis = this.$body.find(".pd-kpis").html(cards.map((card) => d.kpi(card)).join(""));
		cards.forEach((card) => {
			if (card.clickable === false) return;
			$kpis.find(`.pd-kpi[data-key="${card.key}"]`).on("click", (e) => {
				const sub = $(e.target).closest("a[data-sub]").attr("data-sub");
				if (sub === "no_supplier") return this.open_planning({ supplier: "__none__" });
				if (sub === "no_lead_time") return this.open_planning({ missing_lead_time: 1 });
				card.open();
			});
		});
	}

	render_run() {
		const run = this.data.active_run;
		const d = this.d;
		let body;
		if (!run.name) {
			body = d.empty(
				__("No approved run"),
				`${__("Planning uses calculated parameters until a run is approved.")}<br><a class="pd-link pd-new-run">${__("Create a Reorder Parameter Run")}</a>`,
				"📋"
			);
		} else {
			body = `
				<dl class="pd-facts">
					<dt>${__("Run")}</dt><dd><a class="pd-link pd-open-run">${d.esc(run.name)}</a></dd>
					<dt>${__("Analysis date")}</dt><dd>${d.date(run.analysis_date)}</dd>
					<dt>${__("Items")}</dt><dd>${d.number(run.total_items)}</dd>
					<dt>${__("Changed vs previous")}</dt><dd>${d.number(run.changed_items)}</dd>
					<dt>${__("Overridden")}</dt><dd>${d.number(run.overridden_items)}</dd>
					<dt>${__("Next run due")}</dt><dd>${d.date(run.next_due)} ${run.overdue ? d.pill(__("Due"), "red") : ""}</dd>
				</dl>`;
		}
		const $run = this.$body.find(".pd-run").html(d.panel(__("Active parameter run"), body));
		$run.find(".pd-open-run").on("click", () => frappe.set_route("Form", "Reorder Parameter Run", run.name));
		$run.find(".pd-new-run").on("click", () =>
			frappe.new_doc("Reorder Parameter Run", { company: this.data.company, analysis_date: this.data.analysis_date })
		);
	}

	render_agreements() {
		const { blanket_orders, currency } = this.data;
		const d = this.d;
		let body;
		if (!blanket_orders.length) {
			body = d.empty(
				__("No purchasing agreement in force"),
				__("Submitted Purchasing Blanket Orders valid on this date appear here with how much is drawn."),
				"🤝"
			);
		} else {
			body = `<div class="pd-scroll"><table class="pd-table">
				<thead><tr><th>${__("Agreement")}</th><th>${__("Ends")}</th><th>${__("Drawn")}</th><th class="pd-num">${__("Plan")}</th></tr></thead>
				<tbody>${blanket_orders
					.map((a) => {
						const level = a.percent > 85 ? "danger" : a.percent > 60 ? "warn" : "";
						const flags = [
							a.flags.includes("ending") ? d.pill(__("{0} days left", [a.days_left]), "orange") : "",
							a.flags.includes("nearly_used") ? d.pill(__("85%+ drawn"), "red") : "",
							a.no_exchange_rate ? d.pill(__("No {0} rate", [a.currency]), "gray") : "",
						].join(" ");
						return `<tr class="pd-row-link" data-name="${d.esc(a.blanket_order)}">
							<td><div><b>${d.esc(a.supplier)}</b></div><div class="pd-hint">${d.esc(a.blanket_order)} · ${d.esc(a.currency)}</div><div>${flags}</div></td>
							<td>${d.date(a.to_date)}</td>
							<td style="min-width:110px">${d.bar(a.percent, level)}<div class="pd-hint">${d.percent(a.percent)}</div></td>
							<td class="pd-num">${d.compact(a.planned_value, currency)}</td>
						</tr>`;
					})
					.join("")}</tbody></table></div>`;
		}
		const $panel = this.$body
			.find(".pd-agreements")
			.html(d.panel(__("Purchasing agreements"), body, __("drawn by value, {0}", [currency])));
		$panel.find("tr[data-name]").on("click", (e) => frappe.set_route("Form", "Blanket Order", $(e.currentTarget).attr("data-name")));
	}

	render_alerts() {
		const { alerts } = this.data;
		const d = this.d;
		const items = [];
		const old = alerts.old_requests;
		if (old && old.count) {
			items.push(`<div class="pd-alert pd-row-link pd-old-mr">
				<div class="pd-alert-count" style="color: var(--orange-600)">${old.count}</div>
				<div><b>${__("Old open Purchase Material Requests")}</b><div class="pd-hint">${__(
					"Submitted more than {0} days ago and not ordered; they no longer count against the suggestion. Close or order them.",
					[old.max_age_days]
				)}</div></div></div>`);
		}
		alerts.slow_suppliers.forEach((row) => {
			items.push(`<div class="pd-alert pd-row-link" data-supplier="${d.esc(row.supplier)}">
				<div class="pd-alert-count" style="color: var(--red-600)">+${d.number(row.difference, 0)}</div>
				<div><b>${d.esc(row.supplier)}</b><div class="pd-hint">${__(
					"Median {0} days over the last 90 days ({1} receipts) vs {2} days in the Lead Time Profile",
					[d.number(row.median_days, 0), row.samples, d.number(row.profile_days, 0)]
				)}</div></div></div>`);
		});
		const body = items.length
			? items.join("")
			: d.empty(__("Nothing needs attention"), __("No old open requests, and suppliers deliver within their profiled lead times."));
		const $panel = this.$body.find(".pd-alerts").html(d.panel(__("Alerts"), body));
		$panel.find(".pd-old-mr").on("click", () => d.open_list("Material Request", old.names));
		$panel.find("[data-supplier]").on("click", (e) =>
			d.open_list("Lead Time Profile", null, { supplier: $(e.currentTarget).attr("data-supplier") })
		);
	}

	render_charts() {
		const { charts, currency } = this.data;
		const d = this.d;
		const $supplier = this.$body.find(".pd-chart-supplier");
		if (!charts.by_supplier.length) {
			$supplier.html(d.empty(__("Nothing to buy"), __("No item needs a purchase at the current parameters.")));
		} else {
			const suppliers = charts.by_supplier.map((row) => row[0]);
			const chart = d.chart($supplier[0], {
				type: "bar",
				data: { labels: suppliers, datasets: [{ name: __("Suggested value"), values: charts.by_supplier.map((row) => row[1]) }] },
				colors: ["#2490ef"],
				isNavigable: 1,
				tooltipOptions: { formatTooltipY: (value) => d.money(value, currency) },
				axisOptions: { xAxisMode: "tick", xIsSeries: 0, shortenYAxisNumbers: 1 },
			});
			chart.parent.addEventListener("data-select", (e) => this.open_planning({ supplier: suppliers[e.index] }));
		}

		const risk = charts.risk_by_class;
		const has_risk = Object.values(risk.values).some((values) => values.some(Boolean));
		const $risk = this.$body.find(".pd-chart-risk");
		if (!has_risk) {
			$risk.html(d.empty(__("No items"), __("No active stock items in this company.")));
		} else {
			d.chart($risk[0], {
				type: "bar",
				data: {
					labels: risk.classes,
					datasets: ["High", "Medium", "Low"].map((name) => ({ name: __(name), values: risk.values[name] })),
				},
				colors: ["#e24c4c", "#f8a33a", "#48bb74"],
				barOptions: { stacked: 1, spaceRatio: 0.4 },
			});
		}

		const plan = charts.plan_vs_actual;
		const $plan = this.$body.find(".pd-chart-plan");
		if (!plan.has_plan && !plan.actual.some(Boolean)) {
			$plan.html(d.empty(__("No orders or agreements this year"), __("Purchase Orders and Purchasing Blanket Orders of the year show here."), "📈"));
		} else {
			d.chart($plan[0], {
				type: "axis-mixed",
				data: {
					labels: moment.monthsShort(),
					datasets: [
						{ name: __("Purchase Orders"), chartType: "bar", values: plan.actual },
						{ name: __("Agreement plan"), chartType: "line", values: plan.plan },
					],
				},
				colors: ["#5e64ff", "#f8a33a"],
				lineOptions: { regionFill: 0, dotSize: 4 },
				tooltipOptions: { formatTooltipY: (value) => d.money(value, currency) },
				axisOptions: { xIsSeries: 1, shortenYAxisNumbers: 1 },
			});
			if (plan.missing_exchange_rate) {
				$plan.append(`<div class="pd-hint">${__("Some agreements have no exchange rate and count as 0 in the plan.")}</div>`);
			}
		}
	}

	render_top_items() {
		const { top_items, currency } = this.data;
		const d = this.d;
		const colors = { High: "red", Medium: "orange", Low: "green" };
		const body = top_items.length
			? `<div class="pd-scroll"><table class="pd-table">
				<thead><tr>
					<th>${__("Item")}</th><th>${__("Supplier")}</th><th>${__("ABC")}</th>
					<th class="pd-num">${__("Stock")}</th><th class="pd-num">${__("Suggested Qty")}</th>
					<th class="pd-num">${__("Value")}</th><th>${__("Risk")}</th>
				</tr></thead>
				<tbody>${top_items
					.map(
						(row) => `<tr class="pd-row-link" data-item="${d.esc(row.item_code)}">
							<td><b>${d.esc(row.item_code)}</b><div class="pd-hint">${d.esc(row.item_name || "")}</div></td>
							<td>${d.esc(row.supplier || __("No supplier"))}</td>
							<td>${d.esc(row.abc_class || "")}</td>
							<td class="pd-num">${d.number(row.current_stock)}</td>
							<td class="pd-num"><b>${d.number(row.suggested_purchase)}</b></td>
							<td class="pd-num">${d.money(row.suggested_value, currency)}</td>
							<td>${d.pill(__(row.stockout_risk), colors[row.stockout_risk] || "gray")}</td>
						</tr>`
					)
					.join("")}</tbody></table></div>`
			: d.empty(__("Nothing to buy now"), __("Stock and open orders cover every item's target."));
		const $panel = this.$body
			.find(".pd-top-items")
			.html(d.panel(__("Top 10 items to buy now"), body, __("highest risk first, then value · click to open in the planning screen")));
		$panel.find("tr[data-item]").on("click", (e) => this.open_planning({ search: $(e.currentTarget).attr("data-item") }));
	}
}
