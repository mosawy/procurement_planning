# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Stock-out detection and demand month selection.

Pure functions only (no database access). A month in which the item was out of
stock for most of its days records low or zero sales because nothing could be
sold, not because nobody wanted it. Such months are left out of the average.
"""

import calendar
from datetime import date, timedelta

# A month counts as a stock-out month when the end-of-day balance was zero or
# below on at least this share of its days. Overridden by company settings.
DEFAULT_STOCKOUT_DAY_RATIO = 0.5


def month_bounds(month_key):
	year, month = (int(part) for part in month_key.split("-"))
	return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def opening_balance(current_balance, movements_since_opening):
	"""Balance at the start of the first movement window.

	current_balance is today's balance; movements_since_opening are every stock
	movement from the opening date up to now, so walking them back gives the
	opening balance without reading the whole ledger history.
	"""
	return current_balance - sum(qty for _posting_date, qty in movements_since_opening)


def count_stockout_days(opening, movements, month_keys, last_day=None):
	"""End-of-day stock-out days per month.

	opening: balance before the first day of the first month.
	movements: [(posting_date, qty)] in any order; movements after the last month
	are ignored. last_day caps the count (days after it are not counted), for the
	month that contains the analysis date.

	Returns {month_key: (days_out, days_counted)}.
	"""
	if not month_keys:
		return {}

	first_day = month_bounds(month_keys[0])[0]
	period_end = month_bounds(month_keys[-1])[1]
	if last_day and last_day < period_end:
		period_end = last_day

	daily = {}
	balance = opening
	for posting_date, qty in movements:
		if posting_date < first_day:
			balance += qty
		elif posting_date <= period_end:
			daily[posting_date] = daily.get(posting_date, 0) + qty

	result = {}
	for key in month_keys:
		start, end = month_bounds(key)
		end = min(end, period_end)
		days_out = days_counted = 0
		day = start
		while day <= end:
			balance += daily.get(day, 0)
			days_counted += 1
			if balance <= 0:
				days_out += 1
			day += timedelta(days=1)
		result[key] = (days_out, days_counted)
	return result


def stockout_months(stockout_days, ratio=DEFAULT_STOCKOUT_DAY_RATIO):
	"""Month keys where the stock-out share reached the ratio."""
	return {
		key
		for key, (days_out, days_counted) in stockout_days.items()
		if days_counted and days_out / days_counted >= ratio
	}


def select_demand_months(eligible_keys, stockout_keys, monthly_sales):
	"""Months and net sales used for the average.

	Stock-out months are left out unless every eligible month is a stock-out
	month; then they are all kept, since no better evidence exists.

	Returns (used_keys, net_sales, excluded_keys, all_months_stockout).
	"""
	excluded = [key for key in eligible_keys if key in stockout_keys]
	used = [key for key in eligible_keys if key not in stockout_keys]
	all_months_stockout = bool(eligible_keys) and not used

	if all_months_stockout:
		used, excluded = list(eligible_keys), []

	net_sales = sum(monthly_sales.get(key, 0) for key in used)
	return used, net_sales, excluded, all_months_stockout
