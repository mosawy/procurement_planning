// Copyright (c) 2026, Golive-Solutions and contributors
// For license information, please see license.txt

// Shared building blocks of the Planned Purchasing and Back-to-Back dashboards.

frappe.provide("procurement_planning.dashboard");

(() => {
	const esc = (value) => frappe.utils.escape_html(value === null || value === undefined ? "" : String(value));

	const d = procurement_planning.dashboard;
	d.esc = esc;

	d.money = (value, currency) =>
		value === null || value === undefined ? "—" : format_currency(value, currency, 0);

	d.number = (value, decimals = 0) =>
		value === null || value === undefined ? "—" : format_number(value, null, decimals);

	d.percent = (value) => (value === null || value === undefined ? "—" : `${format_number(value, null, 1)}%`);

	// Compact money for KPI cards: 1.2M, 340K.
	d.compact = (value, currency) => {
		if (value === null || value === undefined) return "—";
		const abs = Math.abs(value);
		const symbol = currency ? get_currency_symbol(currency) || currency : "";
		let text;
		if (abs >= 1e6) text = `${format_number(value / 1e6, null, 2)}M`;
		else if (abs >= 1e4) text = `${format_number(value / 1e3, null, 1)}K`;
		else text = format_number(value, null, 0);
		return symbol ? `${symbol} ${text}` : text;
	};

	d.date = (value) => (value ? frappe.datetime.str_to_user(value) : "—");

	d.kpi = ({ key, label, value, sub, accent = "gray", title, clickable = true }) => `
		<div class="pd-kpi pd-accent-${accent} ${clickable ? "" : "pd-static"}" data-key="${esc(key)}"
			title="${esc(title || "")}" role="${clickable ? "button" : ""}" tabindex="${clickable ? 0 : -1}">
			<div class="pd-kpi-label">${esc(label)}</div>
			<div class="pd-kpi-value">${value}</div>
			<div class="pd-kpi-sub">${sub || "&nbsp;"}</div>
		</div>`;

	d.panel = (title, body, hint) => `
		<div class="pd-panel">
			<div class="pd-panel-title"><span>${esc(title)}</span>${hint ? `<span class="pd-hint">${hint}</span>` : ""}</div>
			${body}
		</div>`;

	d.empty = (title, text, icon = "✓") => `
		<div class="pd-empty">
			<div class="pd-empty-icon">${icon}</div>
			<div class="pd-empty-title">${esc(title)}</div>
			<div>${text || ""}</div>
		</div>`;

	d.pill = (text, color) => `<span class="pd-pill pd-pill-${color}">${esc(text)}</span>`;

	d.bar = (percent, level = "") =>
		`<div class="pd-bar ${level ? `pd-bar-${level}` : ""}"><span style="width:${Math.max(0, Math.min(100, percent || 0))}%"></span></div>`;

	// Open a list filtered on the given document names (or the plain list).
	d.open_list = (doctype, names, extra) => {
		const options = Object.assign({}, extra || {});
		if (names && names.length) options.name = ["in", names];
		frappe.route_options = options;
		frappe.set_route("List", doctype);
	};

	d.open_report = (report, filters) => {
		frappe.route_options = filters || {};
		frappe.set_route("query-report", report);
	};

	d.chart = (el, options) => {
		$(el).empty();
		return new frappe.Chart(el, Object.assign({ height: 260, animate: 1, axisOptions: { xIsSeries: 0 } }, options));
	};

	d.loading = () => `<div class="pd-loading">${__("Loading…")}</div>`;
})();
