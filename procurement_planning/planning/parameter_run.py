# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Calculation, approval and activation of Reorder Parameter Runs."""

import frappe
from frappe import _
from frappe.utils import cint, flt, now_datetime

RUN = "Reorder Parameter Run"
LINE = "Reorder Parameter Line"
REALTIME_EVENT = "reorder_parameter_run_calculated"

SUPPLIER_LAST_PO = "Last PO"
SUPPLIER_MANUAL = "Manual"

LINE_FIELDS = (
	"run",
	"company",
	"item_code",
	"item_name",
	"abc_class",
	"supplier",
	"supplier_source",
	"lead_time_days",
	"lead_time_source",
	"ams",
	"ads",
	"months_used",
	"stockout_months",
	"calculated_safety_stock",
	"calculated_reorder_level",
	"calculated_target_stock",
	"previous_reorder_level",
	"previous_target_stock",
	"change_percent",
	"safety_stock",
	"reorder_level",
	"target_stock",
	"is_overridden",
	"warnings",
)


def enqueue_calculation(run_name):
	doc = frappe.get_doc(RUN, run_name)
	doc.check_permission("write")
	if doc.docstatus != 0:
		frappe.throw(_("Only a draft run can be calculated"))
	if doc.status == "Calculating":
		frappe.throw(_("This run is already being calculated"))

	doc.db_set("status", "Calculating")
	frappe.enqueue(
		"procurement_planning.planning.parameter_run.calculate",
		queue="long",
		timeout=3600,
		run_name=run_name,
		user=frappe.session.user,
		enqueue_after_commit=True,
	)


def calculate(run_name, user=None):
	"""Replace the run's lines with freshly calculated parameters."""
	from procurement_planning.planning import api

	doc = frappe.get_doc(RUN, run_name)
	try:
		settings = api.get_settings(
			doc.company,
			doc.item_group,
			# Int fields store 0 when left blank: 0 means "use the company settings".
			cint(doc.analysis_months) or None,
			cint(doc.safety_stock_days) or None,
			cint(doc.review_period_days) or None,
			analysis_date=doc.analysis_date,
		)
		results = api.analyse(settings, use_approved=False)
		previous = _previous_parameters(doc)

		rows = []
		changed = 0
		for result in results:
			line = _line_values(doc, result, previous.get(result.item_code))
			if line is None:
				continue
			if line.pop("_new_item") or abs(line["change_percent"]) > 1e-9:
				changed += 1
			rows.append(line)

		frappe.db.delete(LINE, {"run": run_name})
		_bulk_insert_lines(rows)

		doc.reload()
		doc.db_set(
			{
				"status": "Ready",
				"analysis_months": settings.analysis_months,
				"safety_stock_days": settings.safety_stock_days,
				"review_period_days": settings.review_period_days,
				"total_items": len(rows),
				"changed_items": changed,
				"overridden_items": 0,
				"last_calculated_on": now_datetime(),
			}
		)
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value(RUN, run_name, "status", "Draft")
		frappe.db.commit()
		frappe.log_error(title=_("Reorder Parameter Run {0} failed").format(run_name))
		_notify(run_name, user, failed=True)
		raise

	_notify(run_name, user)


def _notify(run_name, user, failed=False):
	if user:
		frappe.publish_realtime(REALTIME_EVENT, {"run": run_name, "failed": failed}, user=user)


def _line_values(doc, result, previous):
	"""Line fields for one analysed item, or None when the item needs no parameters."""
	proposed = result.proposed
	calculated = (
		proposed["calculated_safety_stock"],
		proposed["calculated_reorder_level"],
		proposed["calculated_target_stock"],
	)
	if not any(calculated) and not previous:
		return None

	# Float and Int columns are NOT NULL in Frappe: an item new to this run gets 0.
	previous_reorder = flt(previous.reorder_level) if previous else 0
	previous_target = flt(previous.target_stock) if previous else 0
	reorder_level = calculated[1]
	if previous_reorder:
		change_percent = (reorder_level - previous_reorder) / previous_reorder * 100
	else:
		change_percent = 100 if reorder_level and previous is not None else 0

	return {
		"_new_item": previous is None,
		"run": doc.name,
		"company": doc.company,
		"item_code": result.item_code,
		"item_name": result.item_name,
		"abc_class": result.abc_class,
		"supplier": result.supplier,
		"supplier_source": result.supplier_source,
		"lead_time_days": cint(result.lead_time_days),
		"lead_time_source": result.lead_time_source or "Fallback",
		"ams": flt(proposed["ams"], 4),
		"ads": flt(proposed["ads"], 6),
		"months_used": result.eligible_months,
		"stockout_months": len(result.stockout_months or []),
		"calculated_safety_stock": calculated[0],
		"calculated_reorder_level": calculated[1],
		"calculated_target_stock": calculated[2],
		"previous_reorder_level": previous_reorder,
		"previous_target_stock": previous_target,
		"change_percent": flt(change_percent, 2),
		"safety_stock": calculated[0],
		"reorder_level": calculated[1],
		"target_stock": calculated[2],
		"is_overridden": 0,
		"warnings": ", ".join(
			code
			for code in proposed["warnings"]
			if code not in ("LATE_PO", "OVERDUE_PO", "IN_TRANSIT", "ETA_PASSED", "UNDATED_PO", "PO_BEYOND_HORIZON", "FUTURE_SALES_ORDERS")
		),
	}


def _bulk_insert_lines(rows):
	if not rows:
		return

	now = now_datetime()
	user = frappe.session.user
	fields = ["name", "creation", "modified", "owner", "modified_by", "docstatus", "idx", *LINE_FIELDS]
	values = [
		[frappe.generate_hash(length=10), now, now, user, user, 0, idx, *(row[field] for field in LINE_FIELDS)]
		for idx, row in enumerate(rows, start=1)
	]
	frappe.db.bulk_insert(LINE, fields, values)


def _previous_parameters(doc):
	"""Approved parameters of the latest other submitted run of the company: {item_code: row}."""
	previous_run = frappe.db.get_value(
		RUN,
		{"company": doc.company, "docstatus": 1, "name": ("!=", doc.name)},
		"name",
		order_by="is_active desc, analysis_date desc, modified desc",
	)
	if not previous_run:
		return {}

	rows = frappe.get_all(
		LINE, filters={"run": previous_run}, fields=["item_code", "reorder_level", "target_stock"]
	)
	return {row.item_code: row for row in rows}


def activate(doc):
	"""Make an approved run the one the planning screen uses for its company."""
	frappe.db.sql(
		"""update `tabReorder Parameter Run` set is_active = 0
		where company = %s and name != %s and is_active = 1""",
		(doc.company, doc.name),
	)
	doc.db_set("is_active", 1)


def reactivate_latest(company, exclude):
	"""After a cancellation, the latest remaining approved run becomes active."""
	latest = frappe.db.get_value(
		RUN,
		{"company": company, "docstatus": 1, "name": ("!=", exclude)},
		"name",
		order_by="analysis_date desc, modified desc",
	)
	if latest:
		frappe.db.set_value(RUN, latest, "is_active", 1)
	return latest


def apply_suppliers(doc):
	"""Save inferred or manually chosen line suppliers as the Item's default supplier for the company."""
	lines = frappe.get_all(
		LINE,
		filters={
			"run": doc.name,
			"supplier": ("is", "set"),
			"supplier_source": ("in", (SUPPLIER_LAST_PO, SUPPLIER_MANUAL)),
		},
		fields=["item_code", "supplier"],
	)

	for line in lines:
		existing = frappe.db.get_value(
			"Item Default",
			{"parent": line.item_code, "parenttype": "Item", "company": doc.company},
			["name", "default_supplier"],
			as_dict=True,
		)
		if existing:
			if existing.default_supplier != line.supplier:
				frappe.db.set_value("Item Default", existing.name, "default_supplier", line.supplier)
			continue

		next_idx = (
			cint(
				frappe.db.sql(
					"select max(idx) from `tabItem Default` where parent = %s and parenttype = 'Item'",
					line.item_code,
				)[0][0]
			)
			+ 1
		)
		frappe.get_doc(
			{
				"doctype": "Item Default",
				"parent": line.item_code,
				"parenttype": "Item",
				"parentfield": "item_defaults",
				"idx": next_idx,
				"company": doc.company,
				"default_supplier": line.supplier,
			}
		).db_insert()

	return len(lines)


def count_overrides(run_name):
	missing_reason = frappe.db.count(
		LINE, {"run": run_name, "is_overridden": 1, "override_reason": ("is", "not set")}
	)
	overridden = frappe.db.count(LINE, {"run": run_name, "is_overridden": 1})
	return overridden, missing_reason


def run_is_editable(run_name):
	return cint(frappe.db.get_value(RUN, run_name, "docstatus")) == 0
