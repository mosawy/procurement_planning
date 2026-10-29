# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Derive lead times from received Purchase Orders into Lead Time Profiles."""

import frappe
from frappe import _
from frappe.utils import add_months, cint, getdate, today

from procurement_planning.planning import data_sources
from procurement_planning.planning.lead_time import summarise_lead_times
from procurement_planning.planning.settings import get_company_settings

SOURCE_DERIVED = "Derived"
SOURCE_MANUAL = "Manual"


def derive_lead_times(company, as_of=None):
	"""Add a Derived entry to the Lead Time Profile of every supplier and every
	supplier + brand with enough received Purchase Orders.

	A profile whose latest entry is Manual is left alone. An entry is only added
	when the derived value changed. A derived entry applies from the start of
	the history window it was calculated from; when the latest derived entry
	already starts on or after that date, it is replaced instead.
	"""
	if not frappe.has_permission("Company", "read", company):
		frappe.throw(_("Not permitted to read Company {0}").format(company), frappe.PermissionError)

	settings = get_company_settings(company)
	as_of = getdate(as_of or today())
	from_date = getdate(add_months(as_of, -settings.lead_time_history_months))

	samples = data_sources.get_lead_time_samples(company, from_date, as_of)
	derived = summarise_lead_times(samples, settings.lead_time_min_samples)

	counts = dict(created=0, updated=0, unchanged=0, skipped_manual=0)
	for (supplier, brand), values in sorted(derived.items(), key=lambda item: (item[0][0], item[0][1] or "")):
		counts[_upsert_profile(company, supplier, brand, values, from_date)] += 1

	return dict(
		counts,
		samples=len(samples),
		groups=len(derived),
		from_date=from_date,
		to_date=as_of,
		min_samples=settings.lead_time_min_samples,
	)


def _upsert_profile(company, supplier, brand, values, window_start):
	name = frappe.db.get_value(
		"Lead Time Profile",
		{"company": company, "supplier": supplier, "brand": brand or ("is", "not set")},
		"name",
	)
	entry = {
		# The value describes the whole history window, so it applies from its start.
		"from_date": window_start,
		"lead_time_days": values["lead_time_days"],
		"source": SOURCE_DERIVED,
		"sample_count": values["sample_count"],
		"p90_lead_time_days": values["p90_lead_time_days"],
		"reason": _("Median of {0} received Purchase Orders").format(values["sample_count"]),
	}

	if not name:
		doc = frappe.new_doc("Lead Time Profile")
		doc.update({"company": company, "supplier": supplier, "brand": brand})
		doc.append("entries", entry)
		doc.insert()
		return "created"

	doc = frappe.get_doc("Lead Time Profile", name)
	latest = max(doc.entries, key=lambda row: getdate(row.from_date)) if doc.entries else None

	if latest and latest.source == SOURCE_MANUAL:
		return "skipped_manual"

	if latest and cint(latest.lead_time_days) == values["lead_time_days"]:
		return "unchanged"

	if latest and getdate(latest.from_date) >= window_start:
		latest.update(entry)
	else:
		doc.append("entries", entry)
	doc.save()
	return "updated"
