app_name = "procurement_planning"
app_title = "Procurement Planning"
app_publisher = "Golive-Solutions"
app_description = "Procurement Planning"
app_email = "info@Golive-Solutions.com"
app_license = "MIT"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/procurement_planning/css/procurement_planning.css"
# app_include_js = "/assets/procurement_planning/js/procurement_planning.js"

# include js, css files in header of web template
# web_include_css = "/assets/procurement_planning/css/procurement_planning.css"
# web_include_js = "/assets/procurement_planning/js/procurement_planning.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "procurement_planning/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
doctype_js = {
	"Quotation": "public/js/quotation.js",
	"Sales Order": "public/js/sales_order.js",
}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "procurement_planning.utils.jinja_methods",
# 	"filters": "procurement_planning.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "procurement_planning.install.before_install"
# after_install = "procurement_planning.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "procurement_planning.uninstall.before_uninstall"
# after_uninstall = "procurement_planning.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "procurement_planning.utils.before_app_install"
# after_app_install = "procurement_planning.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "procurement_planning.utils.before_app_uninstall"
# after_app_uninstall = "procurement_planning.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "procurement_planning.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

has_permission = {
	"Prepared Report": "procurement_planning.permissions.prepared_report_has_permission",
}

# DocType Class
# ---------------
# Override standard doctype classes

# override_doctype_class = {
# 	"ToDo": "custom_app.overrides.CustomToDo"
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

doc_events = {
	"Prepared Report": {
		"before_insert": "procurement_planning.permissions.validate_prepared_report",
	},
	"Custom Role": {
		"validate": "procurement_planning.permissions.validate_custom_role",
	},
	"Quotation": {
		"validate": "procurement_planning.planning.back_to_back.validate_quotation",
		"before_submit": "procurement_planning.planning.back_to_back.before_submit_quotation",
	},
}

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"procurement_planning.tasks.all"
# 	],
# 	"daily": [
# 		"procurement_planning.tasks.daily"
# 	],
# 	"hourly": [
# 		"procurement_planning.tasks.hourly"
# 	],
# 	"weekly": [
# 		"procurement_planning.tasks.weekly"
# 	],
# 	"monthly": [
# 		"procurement_planning.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "procurement_planning.install.before_tests"

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "procurement_planning.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "procurement_planning.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["procurement_planning.utils.before_request"]
# after_request = ["procurement_planning.utils.after_request"]

# Job Events
# ----------
# before_job = ["procurement_planning.utils.before_job"]
# after_job = ["procurement_planning.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"procurement_planning.auth.validate"
# ]

# Installation
# ------------

after_install = "procurement_planning.install.after_install"
after_migrate = "procurement_planning.install.after_migrate"
