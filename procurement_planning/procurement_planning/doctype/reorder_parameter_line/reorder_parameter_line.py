# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from procurement_planning.planning.parameter_run import SUPPLIER_MANUAL, run_is_editable

PARAMETERS = (
	("safety_stock", "calculated_safety_stock"),
	("reorder_level", "calculated_reorder_level"),
	("target_stock", "calculated_target_stock"),
)


class ReorderParameterLine(Document):
	def validate(self):
		# Calculation writes lines with bulk_insert, which skips validate: a new line here was made by hand.
		if self.is_new():
			frappe.throw(_("Reorder Parameter Lines are created by calculating a Reorder Parameter Run"))
		if not run_is_editable(self.run):
			frappe.throw(_("Run {0} is approved or cancelled; its lines cannot change").format(self.run))

		for fieldname, _calculated in PARAMETERS:
			if flt(self.get(fieldname)) < 0:
				frappe.throw(_("{0} cannot be negative").format(_(self.meta.get_label(fieldname))))

		if flt(self.reorder_level) > flt(self.target_stock):
			frappe.throw(_("Reorder Level cannot be above Target Stock"))

		self.is_overridden = int(
			any(abs(flt(self.get(field)) - flt(self.get(calculated))) > 1e-9 for field, calculated in PARAMETERS)
		)
		if self.is_overridden and not (self.override_reason or "").strip():
			frappe.throw(_("Enter an Override Reason for changing the calculated values"))

		before = self.get_doc_before_save()
		if before and before.supplier != self.supplier:
			self.supplier_source = SUPPLIER_MANUAL

	def on_trash(self):
		if not run_is_editable(self.run):
			frappe.throw(_("Run {0} is approved or cancelled; its lines cannot be deleted").format(self.run))
