# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Company planning settings with defaults when no Procurement Planning Settings exists."""

import frappe
from frappe.utils import cint, flt

from procurement_planning.planning.demand_history import DEFAULT_STOCKOUT_DAY_RATIO
from procurement_planning.planning.lead_time import DEFAULT_MIN_SAMPLES
from procurement_planning.planning.proposed_calculations import DEFAULT_LATE_PO_TOLERANCE_DAYS

SETTINGS_DOCTYPE = "Procurement Planning Settings"

DEFAULTS = {
	"analysis_months": 12,
	"safety_stock_days": 45,
	"review_period_days": 30,
	"stockout_day_ratio": DEFAULT_STOCKOUT_DAY_RATIO * 100,
	"late_po_tolerance_days": DEFAULT_LATE_PO_TOLERANCE_DAYS,
	"exclude_back_to_back": 1,
	"default_lead_time_days": 0,
	"lead_time_history_months": 24,
	"lead_time_min_samples": DEFAULT_MIN_SAMPLES,
	"pending_mr_max_age_days": 90,
	"supplier_history_months": 24,
	"default_purchase_warehouse": None,
	"default_landed_cost_percent": 10,
	"fx_buffer_percent": 2,
	"delivery_buffer_days": 7,
	"default_margin_percent": 20,
	"minimum_margin_percent": 10,
	"below_minimum_rate_role": None,
}

INT_FIELDS = (
	"analysis_months",
	"safety_stock_days",
	"review_period_days",
	"late_po_tolerance_days",
	"exclude_back_to_back",
	"default_lead_time_days",
	"lead_time_history_months",
	"lead_time_min_samples",
	"pending_mr_max_age_days",
	"supplier_history_months",
	"delivery_buffer_days",
)

FLOAT_FIELDS = (
	"stockout_day_ratio",
	"default_landed_cost_percent",
	"fx_buffer_percent",
	"default_margin_percent",
	"minimum_margin_percent",
)


def get_company_settings(company):
	"""frappe._dict of every setting for the company; missing values use DEFAULTS."""
	values = frappe._dict(DEFAULTS)
	values.company = company
	values.exists = False

	if company and frappe.db.exists("DocType", SETTINGS_DOCTYPE) and frappe.db.exists(SETTINGS_DOCTYPE, company):
		doc = frappe.db.get_value(SETTINGS_DOCTYPE, company, list(DEFAULTS), as_dict=True) or {}
		for key, value in doc.items():
			if value not in (None, ""):
				values[key] = value
		values.exists = True

	for key in INT_FIELDS:
		values[key] = cint(values[key])
	for key in FLOAT_FIELDS:
		values[key] = flt(values[key])
	return values
