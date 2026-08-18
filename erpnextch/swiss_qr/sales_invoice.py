"""Frappe glue: QR-bill for Sales Invoice.

The reference is frozen onto the invoice at submit time (GeBüV: submitted
documents are immutable) into the ``swiss_qr_reference`` Custom Field. It later
comes back in camt files as ``RmtInf/Strd/CdtrRefInf/Ref`` and is matched
against ``Bank Transaction.reference_number`` — a direct lookup, so it must be
persisted, not derived at print time.
"""

import frappe

from erpnextch.swiss_qr import reference as ref
from erpnextch.swiss_qr.payload import Party, QRBillData
from erpnextch.swiss_qr.render import render_qr_svg_data_uri, render_svg_data_uri

QRR_BASE_DIGITS = ref.QRR_LENGTH - 1


def on_submit_set_reference(doc, method=None):
	"""doc_events hook: freeze the payment reference at submit time."""
	iban = get_company_iban(doc.company)
	if not iban or doc.currency not in ("CHF", "EUR"):
		return
	if ref.is_qr_iban(iban):
		value = ref.generate_qrr(_qrr_base(doc.name))
	else:
		value = ref.generate_scor(_scor_payload(doc.name))
	doc.db_set("swiss_qr_reference", value, update_modified=False)


def _qrr_base(invoice_name: str) -> str:
	"""Deterministic 26-digit QRR base: the digits of the invoice name,
	left-padded with zeros (e.g. ACC-SINV-2026-00042 → …202600042)."""
	digits = "".join(char for char in invoice_name if char.isdigit())
	if not digits:
		frappe.throw(f"Cannot derive a QR reference from invoice name {invoice_name!r}")
	return digits[-QRR_BASE_DIGITS:]


def _scor_payload(invoice_name: str) -> str:
	payload = "".join(char for char in invoice_name if char.isalnum())
	return payload[-(ref.SCOR_MAX_LENGTH - 4) :]


def get_company_iban(company: str) -> str | None:
	return frappe.db.get_value(
		"Bank Account",
		{"company": company, "is_company_account": 1, "is_default": 1, "disabled": 0},
		"iban",
	)


def get_qr_bill_data(doc) -> QRBillData:
	iban = get_company_iban(doc.company)
	if not iban:
		frappe.throw(f"No default company bank account with IBAN for {doc.company}")
	return QRBillData(
		account=iban,
		creditor=_company_party(doc.company),
		amount=doc.rounded_total or doc.grand_total,
		currency=doc.currency,
		debtor=_customer_party(doc),
		reference=doc.get("swiss_qr_reference"),
		message=doc.name,
	)


def qr_bill_svg(doc, language: str = "de") -> str:
	"""Jinja method for print formats: payment-part SVG as a data URI."""
	return render_svg_data_uri(get_qr_bill_data(doc), language=language)


def qr_code_svg(doc, language: str = "de") -> str:
	"""Just the 46×46 mm QR code (no payment slip text) as a data URI, for
	on-screen display such as the dealer portal's invoice detail page."""
	return render_qr_svg_data_uri(get_qr_bill_data(doc), language=language)


def company_logo_data_uri(company: str) -> str:
	"""Jinja method: the company logo inlined as a data URI, so PDF rendering
	never depends on fetching site assets over the network."""
	import base64
	import mimetypes

	file_url = frappe.db.get_value("Company", company, "company_logo")
	if not file_url:
		return ""
	file_name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not file_name:
		return ""
	content = frappe.get_doc("File", file_name).get_content()
	if isinstance(content, str):
		content = content.encode("utf-8")
	mime = mimetypes.guess_type(file_url)[0] or "image/png"
	return f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}"


def formatted_company_iban(company: str) -> str:
	"""Jinja method: the company's IBAN in display grouping (blocks of 4)."""
	iban = get_company_iban(company) or ""
	return " ".join(iban[i : i + 4] for i in range(0, len(iban), 4))


def formatted_qr_reference(doc) -> str:
	"""Jinja method: the frozen reference in its print grouping."""
	value = doc.get("swiss_qr_reference") or ""
	if not value:
		return ""
	if value.startswith("RF"):
		return ref.format_scor(value)
	return ref.format_qrr(value)


def _company_party(company: str) -> Party:
	address_name = frappe.db.get_value(
		"Address",
		{"address_title": company, "is_your_company_address": 1},
		"name",
	)
	if not address_name:
		frappe.throw(f"No company address found for {company}")
	return _party_from_address(company, address_name)


def _customer_party(doc) -> Party | None:
	address_name = doc.get("customer_address") or frappe.db.get_value(
		"Dynamic Link",
		{"link_doctype": "Customer", "link_name": doc.customer, "parenttype": "Address"},
		"parent",
	)
	if not address_name:
		return None
	return _party_from_address(doc.customer_name or doc.customer, address_name)


def _party_from_address(name: str, address_name: str) -> Party:
	address = frappe.get_doc("Address", address_name)
	street, building_number = _split_street(address.address_line1 or "")
	country_code = (frappe.db.get_value("Country", address.country, "code") or "ch").upper()
	return Party(
		name=name,
		street=street,
		building_number=building_number,
		postal_code=address.pincode or "",
		town=address.city or "",
		country=country_code,
	)


def _split_street(line: str) -> tuple[str, str]:
	"""Split "Tödistrasse 9" into street and building number (best effort)."""
	parts = line.rsplit(" ", 1)
	if len(parts) == 2 and parts[1] and parts[1][0].isdigit():
		return parts[0], parts[1]
	return line, ""
