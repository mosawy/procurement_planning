# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from procurement_planning.permissions import ALLOWED_ROLES
from procurement_planning.planning import parameter_run


class ReorderParameterRun(Document):
	def validate(self):
		if self.docstatus == 0 and self.status not in ("Calculating", "Ready"):
			self.status = "Draft"

		for fieldname in ("analysis_months", "safety_stock_days", "review_period_days"):
			value = self.get(fieldname)
			if value not in (None, "") and int(value) < 0:
				frappe.throw(_("{0} cannot be negative").format(_(self.meta.get_label(fieldname))))

	def on_update(self):
		# Changing the inputs of a calculated draft makes its lines stale.
		if self.docstatus == 0 and self.status == "Ready":
			before = self.get_doc_before_save()
			inputs = ("company", "analysis_date", "item_group", "analysis_months", "safety_stock_days", "review_period_days")
			if before and any(str(before.get(f) or "") != str(self.get(f) or "") for f in inputs):
				self.db_set("status", "Draft")

	def before_submit(self):
		if self.status != "Ready" or not frappe.db.exists(parameter_run.LINE, {"run": self.name}):
			frappe.throw(_("Calculate the parameters before approving the run"))

		overridden, missing_reason = parameter_run.count_overrides(self.name)
		if missing_reason:
			frappe.throw(
				_("{0} lines have changed values without an Override Reason").format(missing_reason)
			)
		self.overridden_items = overridden
		self.status = "Approved"

	def on_submit(self):
		parameter_run.activate(self)
		if self.apply_suppliers:
			applied = parameter_run.apply_suppliers(self)
			frappe.msgprint(_("Default supplier saved on {0} items").format(applied), alert=True)

	def on_cancel(self):
		self.db_set({"status": "Cancelled", "is_active": 0})
		latest = parameter_run.reactivate_latest(self.company, self.name)
		if latest:
			frappe.msgprint(_("Run {0} is now the active approved run").format(latest), alert=True)

	def on_trash(self):
		frappe.db.delete(parameter_run.LINE, {"run": self.name})

	@frappe.whitelist()
	def calculate(self):
		frappe.only_for(ALLOWED_ROLES)
		parameter_run.enqueue_calculation(self.name)
		return _("Calculation started. The form refreshes when it finishes.")

	@frappe.whitelist()
	def get_summary(self):
		"""Counts for the form dashboard."""
		lines = frappe.db.sql(
			"""
			select
				count(*) as total,
				sum(case when is_overridden = 1 then 1 else 0 end) as overridden,
				sum(case when supplier_source = 'Last PO' then 1 else 0 end) as inferred_suppliers,
				sum(case when ifnull(supplier, '') = '' then 1 else 0 end) as no_supplier,
				sum(case when lead_time_source in ('Fallback', 'Default') then 1 else 0 end) as weak_lead_time,
				sum(case when abs(change_percent) >= 50 then 1 else 0 end) as big_changes
			from `tabReorder Parameter Line`
			where run = %s
			""",
			self.name,
			as_dict=True,
		)
		return lines[0] if lines else {}
