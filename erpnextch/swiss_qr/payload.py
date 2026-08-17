"""Swiss QR-bill payload (SPC data structure) building and validation.

Pure Python, no Frappe imports — unit-testable without a site.

Field order and limits follow the Swiss Implementation Guidelines QR-bill
(paymentstandards.ch), version 2.2: header (QRType/Version/Coding), account,
creditor (7 lines), ultimate creditor (7 empty lines, not used), amount,
currency, ultimate debtor (7 lines), reference type/reference, unstructured
message, trailer ``EPD``, billing information.

Rendering of the payment part is qrbill's job — this module owns the data,
its validation, and the canonical payload text.
"""

from dataclasses import dataclass, field

from erpnextch.swiss_qr.reference import (
	InvalidReferenceError,
	reference_type_for_iban,
	validate_iban,
)

CRLF = "\r\n"

QR_TYPE = "SPC"
VERSION = "0200"
CODING = "1"  # Latin character set
TRAILER = "EPD"

AMOUNT_MIN = 0.01
AMOUNT_MAX = 999_999_999.99
CURRENCIES = ("CHF", "EUR")

# Characters allowed by the implementation guidelines (v2.2, Latin subset).
_ALLOWED = set(
	"abcdefghijklmnopqrstuvwxyz"
	"ABCDEFGHIJKLMNOPQRSTUVWXYZ"
	"0123456789"
	".,;:'+-/()?*[]{}\\`´~ !\"#%&<>÷=@_$£^"
	"àáâäçèéêëìíîïñòóôöùúûüýßÀÁÂÄÇÈÉÊËÌÍÎÏÒÓÔÖÙÚÛÜÑ"
)

_REPLACEMENTS = str.maketrans({"«": '"', "»": '"', "’": "'", "‘": "'", "–": "-", "—": "-"})


class PayloadError(ValueError):
	"""Invalid QR-bill payload data."""


def sanitize(value: str) -> str:
	"""Map typographic characters to allowed ones, drop the rest."""
	value = (value or "").translate(_REPLACEMENTS)
	return "".join(char for char in value if char in _ALLOWED)


def _require(value: str, max_length: int, label: str) -> str:
	value = sanitize(value).strip()
	if not value:
		raise PayloadError(f"{label} is required")
	if len(value) > max_length:
		raise PayloadError(f"{label} exceeds {max_length} characters: {value!r}")
	return value


def _optional(value: str | None, max_length: int, label: str) -> str:
	value = sanitize(value or "").strip()
	if len(value) > max_length:
		raise PayloadError(f"{label} exceeds {max_length} characters: {value!r}")
	return value


@dataclass
class Party:
	"""Creditor or ultimate debtor, structured address (AdrTp ``S``)."""

	name: str
	street: str = ""
	building_number: str = ""
	postal_code: str = ""
	town: str = ""
	country: str = "CH"

	def lines(self) -> list[str]:
		name = _require(self.name, 70, "Party name")
		street = _optional(self.street, 70, "Street")
		building = _optional(self.building_number, 16, "Building number")
		postal_code = _require(self.postal_code, 16, "Postal code")
		town = _require(self.town, 35, "Town")
		country = (self.country or "").strip().upper()
		if len(country) != 2 or not country.isalpha():
			raise PayloadError(f"Country must be an ISO 3166 two-letter code, got {self.country!r}")
		return ["S", name, street, building, postal_code, town, country]


_EMPTY_PARTY_LINES = [""] * 7


@dataclass
class QRBillData:
	"""Everything needed for one QR-bill payment part."""

	account: str
	creditor: Party
	amount: float | None
	currency: str = "CHF"
	debtor: Party | None = None
	reference: str | None = None
	message: str = ""
	billing_info: str = ""
	reference_type: str = field(init=False, default="NON")

	def validate(self) -> None:
		self.account = validate_iban(self.account)
		if self.account[:2] not in ("CH", "LI"):
			raise PayloadError(f"QR-bill account must be a CH/LI IBAN, got {self.account!r}")
		try:
			self.reference_type = reference_type_for_iban(self.account, self.reference)
		except InvalidReferenceError as exc:
			raise PayloadError(str(exc)) from exc
		if self.currency not in CURRENCIES:
			raise PayloadError(f"Currency must be one of {CURRENCIES}, got {self.currency!r}")
		if self.amount is not None and not AMOUNT_MIN <= self.amount <= AMOUNT_MAX:
			raise PayloadError(f"Amount must be between {AMOUNT_MIN} and {AMOUNT_MAX}, got {self.amount!r}")
		message = _optional(self.message, 140, "Unstructured message")
		billing_info = _optional(self.billing_info, 140, "Billing information")
		if len(message) + len(billing_info) > 140:
			raise PayloadError("Unstructured message and billing information exceed 140 characters combined")
		self.message = message
		self.billing_info = billing_info

	def payload(self) -> str:
		"""The canonical SPC payload, CRLF-separated, as encoded in the QR code."""
		self.validate()
		amount = f"{self.amount:.2f}" if self.amount is not None else ""
		reference = "" if self.reference_type == "NON" else self.reference.replace(" ", "").upper()
		lines = [
			QR_TYPE,
			VERSION,
			CODING,
			self.account,
			*self.creditor.lines(),
			*_EMPTY_PARTY_LINES,  # ultimate creditor: not used
			amount,
			self.currency,
			*(self.debtor.lines() if self.debtor else _EMPTY_PARTY_LINES),
			self.reference_type,
			reference,
			self.message,
			TRAILER,
		]
		if self.billing_info:
			lines.append(self.billing_info)
		return CRLF.join(lines)
