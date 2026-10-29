# Copyright (c) 2026, Golive-Solutions and contributors
# For license information, please see license.txt

"""Access restriction for the Item Reorder Analysis report.

Frappe (v14) reaches report data through three doors:

- live execution: the report's execute() calls frappe.only_for;
- report visibility (run, export, get_script): Report.is_permitted uses the
  report roles, which a Custom Role record replaces; standard report roles can
  only be saved by Administrator, so Custom Role is guarded here;
- Prepared Reports: stored results can be read without any check on the
  report (query_report.run accepts any prepared_report_name), through document
  shares, and through the File owner / add_attachments routes. None of these
  can be closed by a permission hook, so Prepared Reports of this report are
  never created, for any user. The has_permission hook remains as a second
  line for records created by trusted low-level writes.

These hooks only ever deny. has_permission hooks are evaluated in reverse order
and the first non-None answer wins, so returning True would skip Frappe's own
Prepared Report check; None leaves the decision to Frappe.
"""

import frappe
from frappe import _

RESTRICTED_REPORT = "Item Reorder Analysis"
ALLOWED_ROLES = ("System Manager",)


def is_restricted_report(report_name):
	"""True for the restricted report and Custom Reports built on it, at any depth."""
	seen = set()
	while report_name and report_name not in seen:
		if report_name == RESTRICTED_REPORT:
			return True

		seen.add(report_name)
		report = frappe.db.get_value(
			"Report", report_name, ["report_type", "reference_report"], as_dict=True
		)
		if not report or report.report_type != "Custom Report":
			return False

		report_name = report.reference_report

	return False


def has_allowed_role(user=None):
	user = user or frappe.session.user
	return user == "Administrator" or bool(set(ALLOWED_ROLES).intersection(frappe.get_roles(user)))


def prepared_report_has_permission(doc, ptype=None, user=None):
	if is_restricted_report(doc.report_name) and not has_allowed_role(user):
		return False

	return None


def validate_prepared_report(doc, method=None):
	if is_restricted_report(doc.report_name):
		frappe.throw(
			_("Prepared reports are disabled for Report {0}. Run the report directly.").format(
				doc.report_name
			),
			frappe.PermissionError,
		)


def validate_custom_role(doc, method=None):
	if not is_restricted_report(doc.report):
		return

	disallowed = sorted({d.role for d in doc.roles} - set(ALLOWED_ROLES))
	if disallowed:
		frappe.throw(
			_("Report {0} can only be granted to: {1}. Not allowed: {2}").format(
				doc.report, ", ".join(ALLOWED_ROLES), ", ".join(disallowed)
			),
			frappe.PermissionError,
		)
