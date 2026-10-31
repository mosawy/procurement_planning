// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

frappe.pages["back-to-back-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Back-to-Back Dashboard"),
		single_column: true,
	});
	wrapper.dashboard = new BackToBackDashboard(page);
};

const FUNNEL_COLORS = ["#5e64ff", "#6a71ff", "#2490ef", "#1fa2d1", "#17a2a2", "#20a17a", "#3cb371", "#5cb85c", "#2e8b57"];

class BackToBackDashboard {
	constructor(page) {
		this.page = page;
		this.d = procurement_planning.dashboard;
		const quarter_start = moment().startOf("quarter").format("YYYY-MM-DD");
		const quarter_end = moment().endOf("quarter").format("YYYY-MM-DD");
		this.company = page.add_field({
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
			change: () => this.load(),
		});
		this.from_date = page.add_field({
			fieldname: "from_date",
			label: __("From"),
			fieldtype: "Date",
			default: quarter_start,
			change: () => this.load(),
		});
		this.to_date = page.add_field({
			fieldname: "to_date",
			label: __("To"),
			fieldtype: "Date",
			default: quarter_end,
			change: () => this.load(),
		});
		page.set_primary_action(__("Refresh"), () => this.load(true), "refresh");
		page.add_inner_button(__("Sourcing Requests"), () => frappe.set_route("List", "Sourcing Request"));
		page.add_inner_button(__("Order Cost"), () =>
			this.d.open_report("Back-to-Back Order Cost", { company: this.company.get_value() })
		);

		this.$body = $('<div class="pd-page"></div>').appendTo(page.body);
		this.load();
	}

	load(refresh = false) {
		const company = this.company.get_value();
		if (!company) {
			this.$body.html(this.d.empty(__("Choose a company"), __("The dashboard follows back-to-back orders of one company."), "🏢"));
			return;
		}
		const args = { company, from_date: this.from_date.get_value(), to_date: this.to_date.get_value() };
		const key = JSON.stringify(args);
		if (!refresh && key === this.loaded_key) return;
		this.loaded_key = key;
		this.$body.html(this.d.loading());
		frappe
			.call({ method: "procurement_planning.planning.dashboard_data.get_back_to_back_dashboard", args, freeze: refresh })
			.then((r) => {
				this.data = r.message;
				this.render();
			});
	}

	render() {
		const data = this.data;
		const d = this.d;
		this.$body.html(`
			<div class="pd-meta">
				<span>${__("{0} · {1} – {2}", [d.esc(data.company), d.date(data.from_date), d.date(data.to_date)])}</span>
				<span>${__("Shows buying cost and margin: management only")}</span>
			</div>
			<div class="pd-funnel-panel"></div>
			<div class="pd-grid pd-grid-kpi pd-kpis"></div>
			<div class="pd-grid pd-grid-2">
				<div class="pd-panel"><div class="pd-panel-title">${__("Quoted vs actual margin")}<span class="pd-hint">${__("gross margin % by Sales Order month")}</span></div><div class="pd-chart-margin"></div></div>
				<div class="pd-panel"><div class="pd-panel-title">${__("Top suppliers")}<span class="pd-hint">${__("back-to-back Purchase Order value · click a bar")}</span></div><div class="pd-chart-suppliers"></div></div>
			</div>
			<div class="pd-late"></div>
		`);
		this.render_funnel();
		this.render_kpis();
		this.render_charts();
		this.render_late_lines();
	}

	render_funnel() {
		const { funnel } = this.data;
		const d = this.d;
		const first = funnel.stages[0].count;
		let body;
		if (!first) {
			body = d.empty(
				__("No back-to-back quotation in this period"),
				__(
					"Tick Needs Sourcing on quotation lines and use Back-to-Back > Request Sourcing; each quotation is then followed here from request to delivery."
				),
				"🔀"
			);
		} else {
			body = `<div class="pd-funnel">${funnel.stages
				.map((stage, index) => {
					const width = Math.max(6, (stage.count / first) * 100);
					const drop = index ? `−${format_number(stage.drop_off, null, 0)}%` : "";
					return `<div class="pd-funnel-row">
						<div class="pd-funnel-label">${__(stage.label)}</div>
						<div class="pd-funnel-track">
							<div class="pd-funnel-bar" data-index="${index}" title="${__("Open these quotations")}"
								style="width:${width}%; background:${FUNNEL_COLORS[index]}">${stage.count}</div>
						</div>
						<div class="pd-funnel-drop ${stage.drop_off >= 50 ? "pd-drop-high" : ""}">
							${index ? `${drop} · ${format_number(stage.percent, null, 0)}%` : __("cohort")}
						</div>
					</div>`;
				})
				.join("")}</div>`;
		}
		body += `<div class="pd-funnel-foot">
			<span>${__("Win rate")}: <b>${funnel.win_rate === null ? "—" : d.percent(funnel.win_rate)}</b>
				<span class="pd-hint">${__("submitted quotations that became Sales Orders")}</span></span>
			<span><a class="pd-link pd-sr" data-status="Waiting for Offers">${__("Waiting for offers")}: <b>${funnel.waiting}</b></a></span>
			<span><a class="pd-link pd-sr" data-status="Ready">${__("Ready to submit")}: <b>${funnel.ready}</b></a></span>
		</div>`;
		const $panel = this.$body
			.find(".pd-funnel-panel")
			.html(d.panel(__("Back-to-back funnel"), body, __("quotations dated in the period, counted up to the furthest stage reached")));
		$panel.find(".pd-funnel-bar").on("click", (e) => {
			const stage = funnel.stages[cint($(e.currentTarget).attr("data-index"))];
			d.open_list("Quotation", stage.names);
		});
		$panel.find(".pd-sr").on("click", (e) => {
			const status = $(e.currentTarget).attr("data-status");
			d.open_list("Sourcing Request", null, {
				company: this.data.company,
				docstatus: 0,
				status: status === "Ready" ? "Ready" : ["in", ["Draft", "Waiting for Offers"]],
			});
		});
	}

	render_kpis() {
		const { kpis, currency, company } = this.data;
		const d = this.d;
		const cards = [
			{
				key: "turnaround",
				label: __("Sourcing turnaround"),
				value: kpis.turnaround.days === null ? "—" : __("{0} days", [format_number(kpis.turnaround.days, null, 1)]),
				sub: __("average over {0} submitted requests", [kpis.turnaround.count]),
				accent: kpis.turnaround.days === null ? "gray" : kpis.turnaround.days > 5 ? "orange" : "green",
				open: () => d.open_list("Sourcing Request", kpis.turnaround.names),
			},
			{
				key: "late",
				label: __("Late against promise"),
				value: d.number(kpis.late.late),
				sub: __("{0} more at risk (within 7 days)", [kpis.late.at_risk]),
				accent: kpis.late.late ? "red" : kpis.late.at_risk ? "orange" : "green",
				open: () => d.open_report("Back-to-Back Sales Tracker", { company }),
			},
			{
				key: "expiring",
				label: __("Offers expiring ≤ 7 days"),
				value: d.number(kpis.expiring_offers.lines),
				sub: __("chosen offers on open Sourcing Requests"),
				accent: kpis.expiring_offers.lines ? "orange" : "green",
				open: () => d.open_list("Sourcing Request", kpis.expiring_offers.names, { docstatus: 0 }),
			},
			{
				key: "sales",
				label: __("Back-to-back sales"),
				value: d.compact(kpis.sales.value, currency),
				sub: __("{0} gross margin · {1} orders", [d.percent(kpis.sales.margin), kpis.sales.orders]),
				title: d.money(kpis.sales.value, currency),
				accent: "blue",
				open: () => d.open_list("Sales Order", kpis.sales.names),
			},
			{
				key: "excess",
				label: __("Supplier minimum to stock"),
				value: d.compact(kpis.excess.value, currency),
				sub: __("{0} units bought above customer orders", [d.number(kpis.excess.qty)]),
				title: d.money(kpis.excess.value, currency),
				accent: kpis.excess.value ? "purple" : "gray",
				open: () => d.open_list("Purchase Order", kpis.excess.names),
			},
		];
		const $kpis = this.$body.find(".pd-kpis").html(cards.map((card) => d.kpi(card)).join(""));
		cards.forEach((card) => $kpis.find(`.pd-kpi[data-key="${card.key}"]`).on("click", () => card.open()));
	}

	render_charts() {
		const { charts, currency } = this.data;
		const d = this.d;

		const margin = charts.margin_by_month;
		const months = margin.labels.filter((_label, i) => margin.quoted[i] !== null);
		const $margin = this.$body.find(".pd-chart-margin");
		if (!months.length) {
			$margin.html(d.empty(__("No back-to-back Sales Order in this period"), __("Quoted and actual margin appear once orders are submitted."), "📊"));
		} else {
			const pick = (values) => margin.labels.map((_l, i) => values[i]).filter((_v, i) => margin.quoted[i] !== null);
			d.chart($margin[0], {
				type: "line",
				data: {
					labels: months.map((m) => moment(m, "YYYY-MM").format("MMM YYYY")),
					datasets: [
						{ name: __("Quoted"), values: pick(margin.quoted).map((v) => flt(v, 1)) },
						{ name: __("Actual"), values: pick(margin.actual).map((v) => (v === null ? 0 : flt(v, 1))) },
					],
				},
				colors: ["#5e64ff", "#48bb74"],
				lineOptions: { dotSize: 5, regionFill: 0 },
				tooltipOptions: { formatTooltipY: (value) => `${value}%` },
			});
			if (margin.actual.some((v, i) => v === null && margin.quoted[i] !== null)) {
				$margin.append(`<div class="pd-hint">${__("Actual 0 % = no Purchase Order yet for that month's orders.")}</div>`);
			}
		}

		const suppliers = charts.top_suppliers;
		const $suppliers = this.$body.find(".pd-chart-suppliers");
		if (!suppliers.length) {
			$suppliers.html(d.empty(__("No back-to-back Purchase Order in this period"), __("Purchase Orders made from Back-to-Back Material Requests show here."), "🚚"));
		} else {
			const names = suppliers.map((row) => row[0]);
			const chart = d.chart($suppliers[0], {
				type: "bar",
				data: { labels: names, datasets: [{ name: __("PO value"), values: suppliers.map((row) => row[1]) }] },
				colors: ["#17a2a2"],
				isNavigable: 1,
				tooltipOptions: { formatTooltipY: (value) => d.money(value, currency) },
				axisOptions: { xAxisMode: "tick", xIsSeries: 0, shortenYAxisNumbers: 1 },
			});
			chart.parent.addEventListener("data-select", (e) =>
				d.open_report("Back-to-Back Purchase Tracker", { company: this.data.company, supplier: names[e.index] })
			);
		}
	}

	render_late_lines() {
		const { late_lines, late_lines_total, company } = this.data;
		const d = this.d;
		const body = late_lines.length
			? `<div class="pd-scroll"><table class="pd-table">
				<thead><tr>
					<th>${__("Sales Order")}</th><th>${__("Item")}</th><th>${__("Customer")}</th><th>${__("Stage")}</th>
					<th>${__("Promised")}</th><th>${__("Expected Arrival")}</th><th class="pd-num">${__("Days Late")}</th>
				</tr></thead>
				<tbody>${late_lines
					.map(
						(row) => `<tr class="pd-row-link" data-so="${d.esc(row.sales_order)}">
							<td><b>${d.esc(row.sales_order)}</b></td>
							<td>${d.esc(row.item_code)}<div class="pd-hint">${d.esc(row.item_name || "")}</div></td>
							<td>${d.esc(row.customer || "")}</td>
							<td>${d.pill(__(row.stage), row.late ? "red" : "orange")}</td>
							<td>${d.date(row.promised_date)}</td>
							<td>${row.expected_arrival ? d.date(row.expected_arrival) : `<span class="pd-hint">${__("not ordered")}</span>`}</td>
							<td class="pd-num" style="color: var(${row.late ? "--red-600" : "--orange-600"}); font-weight: 700">${
								row.days_late > 0 ? "+" : ""
							}${row.days_late}</td>
						</tr>`
					)
					.join("")}</tbody></table></div>`
			: d.empty(__("Every open line is on track"), __("No sourced Sales Order line is late or within 7 days of its promised date."));
		const hint =
			late_lines_total > late_lines.length
				? __("{0} of {1} lines · click to open the Sales Tracker", [late_lines.length, late_lines_total])
				: __("all open orders, not only this period");
		const $panel = this.$body.find(".pd-late").html(d.panel(__("Late or at-risk lines"), body, hint));
		$panel.find("tr[data-so]").on("click", (e) =>
			d.open_report("Back-to-Back Sales Tracker", { company, sales_order: $(e.currentTarget).attr("data-so") })
		);
	}
}
