# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Reproduction of the original SAP Item Analysis calculations.

Pure functions only (no database access) so they can be tested in isolation.
Every metric is either a number or None; a None value always comes with a
reason in ``unavailable`` and is never replaced by an invented zero.
"""

import math

# SAP uses a fixed 45-day safety factor, independent of the planning filter.
SAP_SAFETY_DAYS = 45
SAP_PERIOD_MONTHS = 12
SAP_PERIOD_DAYS = 365

# Months with positive net sales in the fixed 12-month period -> ABC class.
ABC_THRESHOLDS = ((10, "A"), (8, "B"), (6, "C"), (4, "D"), (2, "E"), (1, "F"))
NON_MOVING_CLASS = "Non-Moving"

# Confirmed class-dependent SAP Min rules: {abc_class: fn(daily_avg, reorder, safety) -> qty}.
# No rule has been confirmed yet, so SAP Min is unavailable for every class.
SAP_MIN_RULES = {}

UNAVAILABLE_GRACE_DAYS = "Grace Days not available"
UNAVAILABLE_PR_FOREIGN = "PR Foreign source not identified"
UNAVAILABLE_NO_SELLING_MONTHS = "No month with positive net sales"
UNAVAILABLE_MIN_RULE = "SAP Min rule not confirmed for this class"


# Absorbs binary floating-point noise only (e.g. 30.000000000000004), not real fractions.
CEIL_TOLERANCE = 1e-9


def ceil_qty(value):
	return math.ceil(value - CEIL_TOLERANCE)


def count_months_with_sales(monthly_net_sales):
	return sum(1 for qty in monthly_net_sales if qty > 0)


def classify_abc(months_with_sales):
	for minimum_months, abc_class in ABC_THRESHOLDS:
		if months_with_sales >= minimum_months:
			return abc_class
	return NON_MOVING_CLASS


def calculate_sap(
	net_sales_12m,
	months_with_sales,
	stock,
	open_po,
	open_so,
	abc_class,
	grace_days=None,
	pr_foreign=None,
):
	"""Original SAP metrics. grace_days and pr_foreign are None when unknown."""
	unavailable = {}
	values = {}

	values["avg_mon"] = net_sales_12m / SAP_PERIOD_MONTHS
	values["daily_avg"] = net_sales_12m / SAP_PERIOD_DAYS
	if months_with_sales > 0:
		values["avg_cont"] = net_sales_12m / months_with_sales
	else:
		values["avg_cont"] = None
		unavailable["avg_cont"] = UNAVAILABLE_NO_SELLING_MONTHS

	daily_avg = values["daily_avg"]
	values["safety"] = ceil_qty(daily_avg * SAP_SAFETY_DAYS)

	if grace_days is None:
		values["reorder"] = None
		unavailable["reorder"] = UNAVAILABLE_GRACE_DAYS
	else:
		values["reorder"] = ceil_qty(daily_avg * grace_days)

	values["max"] = None if values["reorder"] is None else values["reorder"] + values["safety"]
	if values["max"] is None:
		unavailable["max"] = unavailable["reorder"]

	min_rule = SAP_MIN_RULES.get(abc_class)
	if min_rule and values["reorder"] is not None:
		values["min"] = min_rule(daily_avg, values["reorder"], values["safety"])
	else:
		values["min"] = None
		unavailable["min"] = UNAVAILABLE_MIN_RULE if not min_rule else UNAVAILABLE_GRACE_DAYS

	values["miss_qty"] = stock + open_po - open_so

	if pr_foreign is None:
		for metric in ("to_reorder", "rec_qty", "missing_so", "to_reorder_final"):
			values[metric] = None
			unavailable[metric] = UNAVAILABLE_PR_FOREIGN
	else:
		values["missing_so"] = stock + open_po + pr_foreign - open_so
		values["rec_qty"] = max(0, values["avg_mon"] * SAP_PERIOD_MONTHS + open_so - stock - open_po - pr_foreign)
		if values["reorder"] is None:
			values["to_reorder"] = values["to_reorder_final"] = None
			unavailable["to_reorder"] = unavailable["to_reorder_final"] = UNAVAILABLE_GRACE_DAYS
		else:
			values["to_reorder"] = values["missing_so"] - values["reorder"]
			values["to_reorder_final"] = values["to_reorder"] - pr_foreign

	values["unavailable"] = unavailable
	return values
