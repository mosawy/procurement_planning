# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Calculations behind the two purchasing dashboards. Pure functions only."""

import statistics
from datetime import date

RISK_ORDER = {"High": 0, "Medium": 1, "Low": 2}
ENDING_WITHIN_DAYS = 30
NEARLY_USED_PERCENT = 85
AT_RISK_DAYS = 7

FUNNEL_STAGES = (
	"Quotations with sourcing lines",
	"Sent to purchasing",
	"Priced",
	"Quotation submitted",
	"Won (Sales Order)",
	"Purchase requested",
	"Ordered",
	"Received",
	"Delivered",
)


def quarter_range(on_date):
	"""(first, last) day of the calendar quarter of on_date."""
	first_month = (on_date.month - 1) // 3 * 3 + 1
	first = date(on_date.year, first_month, 1)
	last = date(on_date.year + 1, 1, 1) if first_month == 10 else date(on_date.year, first_month + 3, 1)
	return first, date.fromordinal(last.toordinal() - 1)


def first_of_next_month(on_date):
	return date(on_date.year + 1, 1, 1) if on_date.month == 12 else date(on_date.year, on_date.month + 1, 1)


def _month_index(day):
	return day.year * 12 + day.month - 1


def spread_plan_by_month(agreements, year):
	"""{month 1..12: planned value} of agreements over a year.

	agreements: dicts with from_date, to_date and value (company currency). Each
	agreement's value is spread evenly over the calendar months it covers; the
	months that fall in year are kept.
	"""
	result = {month: 0.0 for month in range(1, 13)}
	for agreement in agreements:
		first, last = _month_index(agreement["from_date"]), _month_index(agreement["to_date"])
		if last < first or not agreement.get("value"):
			continue
		share = agreement["value"] / (last - first + 1)
		for index in range(max(first, year * 12), min(last, year * 12 + 11) + 1):
			result[index % 12 + 1] += share
	return result


def agreement_drawdown(lines):
	"""(planned value, ordered value, percent drawn) of an agreement's lines
	[(qty, ordered_qty, rate in company currency)]."""
	planned = sum((qty or 0) * (rate or 0) for qty, _ordered, rate in lines)
	ordered = sum((ordered_qty or 0) * (rate or 0) for _qty, ordered_qty, rate in lines)
	return planned, ordered, (ordered / planned * 100 if planned else 0)


def agreement_flags(to_date, percent_drawn, on_date):
	"""Flags for an agreement: ending within 30 days, more than 85 % drawn."""
	flags = []
	if 0 <= (to_date - on_date).days <= ENDING_WITHIN_DAYS:
		flags.append("ending")
	if percent_drawn > NEARLY_USED_PERCENT:
		flags.append("nearly_used")
	return flags


def slow_suppliers(samples, profiles, limit=5):
	"""Suppliers whose recent receipts are slower than their Lead Time Profile.

	samples: [(supplier, brand, days)] of recent receipts; profiles:
	{(supplier, brand): days}. The supplier's profile is its own (supplier,
	None) entry, else the average of its supplier + brand entries. Returns the
	slowest first: [{supplier, median_days, profile_days, difference, samples}].
	"""
	by_supplier = {}
	for supplier, _brand, days in samples:
		if supplier:
			by_supplier.setdefault(supplier, []).append(days)

	result = []
	for supplier, days in by_supplier.items():
		profile = profiles.get((supplier, None))
		if not profile:
			brand_profiles = [value for (s, b), value in profiles.items() if s == supplier and b and value]
			profile = sum(brand_profiles) / len(brand_profiles) if brand_profiles else None
		if not profile:
			continue
		median = statistics.median(days)
		if median > profile:
			result.append(
				{
					"supplier": supplier,
					"median_days": median,
					"profile_days": round(profile, 1),
					"difference": round(median - profile, 1),
					"samples": len(days),
				}
			)
	result.sort(key=lambda row: (-row["difference"], row["supplier"]))
	return result[:limit]


def top_items_to_buy(rows, limit=10):
	"""Items with a suggested purchase, highest risk first, then by value."""
	buy = [row for row in rows if (row.get("suggested_purchase") or 0) > 0]
	buy.sort(key=lambda row: (RISK_ORDER.get(row.get("stockout_risk"), 3), -(row.get("suggested_value") or 0)))
	return buy[:limit]


def group_totals(rows, key, value, limit=None):
	"""[(key, total)] of value per key, largest first; rows without a key are left out."""
	totals = {}
	for row in rows:
		if row.get(key):
			totals[row[key]] = totals.get(row[key], 0) + (row.get(value) or 0)
	ordered = sorted(((k, v) for k, v in totals.items() if v), key=lambda item: (-item[1], item[0]))
	return ordered[:limit] if limit else ordered


def risk_by_class(rows, classes):
	"""{risk: [count per class]} for a stacked chart."""
	result = {risk: [0] * len(classes) for risk in RISK_ORDER}
	index = {cls: i for i, cls in enumerate(classes)}
	for row in rows:
		risk, cls = row.get("stockout_risk"), row.get("abc_class")
		if risk in result and cls in index:
			result[risk][index[cls]] += 1
	return result


def furthest_stage(flags):
	"""Index of the furthest funnel stage a quotation reached; flags: one bool per
	stage. A later stage counts even if an earlier flag is missing (e.g. a Sales
	Order made without submitting through every step)."""
	reached = [i for i, flag in enumerate(flags) if flag]
	return max(reached) if reached else -1


def funnel(furthest_stages, labels=FUNNEL_STAGES):
	"""Funnel rows (label, count, percent of the first stage, drop-off from the
	previous stage) from each quotation's furthest stage: a quotation counts
	in every stage up to the one it reached."""
	counts = [sum(1 for stage in furthest_stages if stage >= i) for i in range(len(labels))]
	rows = []
	for i, label in enumerate(labels):
		previous = counts[i - 1] if i else counts[0]
		rows.append(
			{
				"label": label,
				"count": counts[i],
				"percent": counts[i] / counts[0] * 100 if counts[0] else 0,
				"drop_off": (previous - counts[i]) / previous * 100 if i and previous else 0,
			}
		)
	return rows


def win_rate(submitted, won):
	return won / submitted * 100 if submitted else None


def margin_percent(sales, cost):
	return (sales - cost) / sales * 100 if sales else None


def is_at_risk(days_late):
	"""Expected arrival within 7 days before the promise (or on it)."""
	return days_late is not None and -AT_RISK_DAYS <= days_late <= 0
