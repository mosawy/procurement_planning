# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Lead time derivation and resolution, and supplier resolution.

Pure functions only (no database access).
"""

import math

DEFAULT_MIN_SAMPLES = 3

SOURCE_ITEM = "Item"
SOURCE_PROFILE = "Profile"
SOURCE_DEFAULT = "Default"

SUPPLIER_ITEM_DEFAULT = "Item Default"
SUPPLIER_ITEM_SUPPLIER = "Item Supplier"
SUPPLIER_LAST_PO = "Last PO"


def percentile(values, share):
	"""Nearest-rank percentile of a non-empty list (share between 0 and 1)."""
	ordered = sorted(values)
	rank = max(1, math.ceil(share * len(ordered)))
	return ordered[rank - 1]


def median(values):
	ordered = sorted(values)
	middle = len(ordered) // 2
	if len(ordered) % 2:
		return ordered[middle]
	return (ordered[middle - 1] + ordered[middle]) / 2


def summarise_lead_times(samples, min_samples=DEFAULT_MIN_SAMPLES):
	"""Lead time per supplier + brand and per supplier.

	samples: [(supplier, brand or None, days)], one per Purchase Order and brand:
	the days from the PO date to its first receipt. Negative days (receipts
	back-dated before the order) are dropped.

	Returns {(supplier, brand or None): {"lead_time_days", "p90_lead_time_days",
	"sample_count"}}. The (supplier, None) key is the supplier over all brands.
	Groups with fewer than min_samples samples are left out.
	"""
	groups = {}
	for supplier, brand, days in samples:
		if not supplier or days is None or days < 0:
			continue
		groups.setdefault((supplier, None), []).append(days)
		if brand:
			groups.setdefault((supplier, brand), []).append(days)

	result = {}
	for key, values in groups.items():
		if len(values) < max(1, min_samples):
			continue
		result[key] = {
			"lead_time_days": int(math.ceil(median(values))),
			"p90_lead_time_days": int(percentile(values, 0.9)),
			"sample_count": len(values),
		}
	return result


def effective_entry(entries, on_date):
	"""Latest entry with from_date on or before on_date: entries are dicts with from_date."""
	valid = [entry for entry in entries if entry["from_date"] and entry["from_date"] <= on_date]
	if not valid:
		return None
	return max(valid, key=lambda entry: (entry["from_date"], entry.get("idx") or 0))


def resolve_lead_time(item_lead_time, supplier, brand, profile_lead_times, default_lead_time=0):
	"""(lead_time_days, source, detail) for one item.

	Order: the Item's own lead time, then a profile for supplier + brand, the
	supplier alone, the brand alone, and finally the company default.
	profile_lead_times: {(supplier or None, brand or None): days}.
	"""
	if item_lead_time and item_lead_time > 0:
		return int(item_lead_time), SOURCE_ITEM, None

	candidates = []
	if supplier and brand:
		candidates.append((supplier, brand))
	if supplier:
		candidates.append((supplier, None))
	if brand:
		candidates.append((None, brand))

	for key in candidates:
		days = profile_lead_times.get(key)
		if days and days > 0:
			return int(days), SOURCE_PROFILE, key

	if default_lead_time and default_lead_time > 0:
		return int(default_lead_time), SOURCE_DEFAULT, None

	return None, None, None


def resolve_supplier(item_default_supplier, item_supplier, last_po_supplier):
	"""(supplier, source) from maintained data first, then the latest Purchase Order."""
	if item_default_supplier:
		return item_default_supplier, SUPPLIER_ITEM_DEFAULT
	if item_supplier:
		return item_supplier, SUPPLIER_ITEM_SUPPLIER
	if last_po_supplier:
		return last_po_supplier, SUPPLIER_LAST_PO
	return None, None
