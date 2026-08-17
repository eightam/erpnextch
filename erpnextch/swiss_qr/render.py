"""Render the QR-bill payment part via the qrbill package (MIT).

No Frappe imports. The spec pins the payment-part geometry to the millimetre
(105×210 mm payment part, 46×46 mm QR, 7×7 mm Swiss cross, font sizes) —
qrbill owns that drawing; we only hand it validated data.
"""

import base64
import io

from qrbill import QRBill

from erpnextch.swiss_qr.payload import QRBillData

LANGUAGES = ("de", "fr", "it", "en")


def _party_dict(party):
	return {
		"name": party.name,
		"street": party.street or None,
		"house_num": party.building_number or None,
		"pcode": party.postal_code,
		"city": party.town,
		"country": party.country,
	}


def render_svg(data: QRBillData, language: str = "de") -> str:
	"""Render the payment part (105×210 mm) as an SVG string."""
	if language not in LANGUAGES:
		raise ValueError(f"Language must be one of {LANGUAGES}, got {language!r}")
	data.validate()
	bill = QRBill(
		account=data.account,
		creditor=_party_dict(data.creditor),
		debtor=_party_dict(data.debtor) if data.debtor else None,
		amount=f"{data.amount:.2f}" if data.amount is not None else None,
		currency=data.currency,
		reference_number=None if data.reference_type == "NON" else data.reference,
		additional_information=data.message or None,
		language=language,
	)
	out = io.StringIO()
	bill.as_svg(out, full_page=False)
	return out.getvalue()


def render_svg_data_uri(data: QRBillData, language: str = "de") -> str:
	"""SVG as a base64 data URI, for embedding in print formats."""
	svg = render_svg(data, language=language)
	return "data:image/svg+xml;base64," + base64.b64encode(svg.encode("utf-8")).decode("ascii")
