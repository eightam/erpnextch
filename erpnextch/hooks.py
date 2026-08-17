app_name = "erpnextch"
app_title = "ERPNext CH"
app_publisher = "8am GmbH"
app_description = "Swiss localisation for ERPNext: QR-bill, camt import, Kontenrahmen KMU, MwSt."
required_apps = ["frappe/erpnext"]
app_email = "lobeck@8am.ch"
app_license = "GPL-3.0"

fixtures = [
	{"dt": "Custom Field", "filters": [["module", "=", "ERPNext CH"]]},
	{"dt": "Print Format", "filters": [["module", "=", "ERPNext CH"]]},
]

doc_events = {
	"Sales Invoice": {
		"on_submit": "erpnextch.swiss_qr.sales_invoice.on_submit_set_reference",
	},
}

jinja = {
	"methods": [
		"erpnextch.swiss_qr.sales_invoice.qr_bill_svg",
		"erpnextch.swiss_qr.sales_invoice.formatted_qr_reference",
	],
}
