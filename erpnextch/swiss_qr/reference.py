"""Payment reference logic for the Swiss QR-bill: QRR and SCOR.

Pure Python, no Frappe imports — unit-testable without a site.

The reference scheme is bound to the account type:

- QR-IBAN (IID in positions 5-9 within 30000-31999) → QRR is mandatory
  (27 digits, Modulo 10 recursive check digit).
- Normal IBAN → SCOR (ISO 11649, "RF" + 2 check digits) or no reference.
  A QRR with a normal IBAN is rejected by the bank.
"""

# Modulo 10 recursive, as defined by the Swiss payment standards.
_MOD10_TABLE = (0, 9, 4, 6, 8, 2, 7, 1, 3, 5)

QRR_LENGTH = 27
SCOR_MAX_LENGTH = 25  # "RF" + 2 check digits + up to 21 alphanumeric chars

QR_IID_RANGE = range(30000, 32000)


class InvalidReferenceError(ValueError):
	"""Invalid payment reference or IBAN/reference mismatch."""


def _clean(value: str) -> str:
	return (value or "").replace(" ", "").upper()


# --- IBAN -------------------------------------------------------------------


def _mod97(value: str) -> int:
	"""ISO 7064 mod 97-10 over a string where letters count as A=10 … Z=35."""
	total = 0
	for char in value:
		if char.isdigit():
			total = (total * 10 + int(char)) % 97
		elif char.isalpha():
			total = (total * 100 + (ord(char) - ord("A") + 10)) % 97
		else:
			raise InvalidReferenceError(f"Invalid character {char!r} in mod-97 input")
	return total


def validate_iban(iban: str) -> str:
	"""Validate an IBAN checksum; return the cleaned IBAN."""
	iban = _clean(iban)
	if len(iban) < 15 or len(iban) > 34 or not iban[:2].isalpha() or not iban[2:4].isdigit():
		raise InvalidReferenceError(f"Malformed IBAN: {iban!r}")
	if _mod97(iban[4:] + iban[:4]) != 1:
		raise InvalidReferenceError(f"IBAN checksum failed: {iban!r}")
	return iban


def is_qr_iban(iban: str) -> bool:
	"""True if the (valid) IBAN is a QR-IBAN: CH/LI with a QR-IID (30000-31999)."""
	iban = validate_iban(iban)
	if iban[:2] not in ("CH", "LI"):
		return False
	return int(iban[4:9]) in QR_IID_RANGE


# --- QRR (QR reference, Modulo 10 recursive) --------------------------------


def mod10_recursive(digits: str) -> int:
	"""Check digit for a digit string, Modulo 10 recursive."""
	if not digits.isdigit():
		raise InvalidReferenceError(f"QRR reference must be numeric, got {digits!r}")
	carry = 0
	for digit in digits:
		carry = _MOD10_TABLE[(carry + int(digit)) % 10]
	return (10 - carry) % 10


def generate_qrr(base: str) -> str:
	"""Build a 27-digit QRR reference from up to 26 digits (left-padded with zeros)."""
	base = _clean(base)
	if not base.isdigit():
		raise InvalidReferenceError(f"QRR base must be numeric, got {base!r}")
	if len(base) > QRR_LENGTH - 1:
		raise InvalidReferenceError(f"QRR base longer than {QRR_LENGTH - 1} digits: {base!r}")
	base = base.zfill(QRR_LENGTH - 1)
	return base + str(mod10_recursive(base))


def validate_qrr(reference: str) -> str:
	"""Validate a 27-digit QRR reference; return it cleaned."""
	reference = _clean(reference)
	if len(reference) != QRR_LENGTH or not reference.isdigit():
		raise InvalidReferenceError(f"QRR must be {QRR_LENGTH} digits, got {reference!r}")
	if mod10_recursive(reference[:-1]) != int(reference[-1]):
		raise InvalidReferenceError(f"QRR check digit failed: {reference!r}")
	return reference


def format_qrr(reference: str) -> str:
	"""Format a QRR for print: blocks of 5, from the right (2 00000 00003 …)."""
	reference = validate_qrr(reference)
	head = len(reference) % 5
	blocks = ([reference[:head]] if head else []) + [
		reference[i : i + 5] for i in range(head, len(reference), 5)
	]
	return " ".join(blocks)


# --- SCOR (ISO 11649 creditor reference) ------------------------------------


def generate_scor(payload: str) -> str:
	"""Build an ISO 11649 creditor reference ("RF" + check digits + payload)."""
	payload = _clean(payload)
	if not payload.isalnum():
		raise InvalidReferenceError(f"SCOR payload must be alphanumeric, got {payload!r}")
	if not payload or len(payload) > SCOR_MAX_LENGTH - 4:
		raise InvalidReferenceError(f"SCOR payload must be 1-{SCOR_MAX_LENGTH - 4} chars, got {payload!r}")
	check = 98 - _mod97(payload + "RF00")
	return f"RF{check:02d}{payload}"


def validate_scor(reference: str) -> str:
	"""Validate an ISO 11649 creditor reference; return it cleaned."""
	reference = _clean(reference)
	if (
		len(reference) < 5
		or len(reference) > SCOR_MAX_LENGTH
		or not reference.startswith("RF")
		or not reference[2:4].isdigit()
		or not reference[4:].isalnum()
	):
		raise InvalidReferenceError(f"Malformed SCOR reference: {reference!r}")
	if _mod97(reference[4:] + reference[:4]) != 1:
		raise InvalidReferenceError(f"SCOR check digits failed: {reference!r}")
	return reference


def format_scor(reference: str) -> str:
	"""Format a SCOR for print: blocks of 4, from the left (RF18 5390 0754 7034)."""
	reference = validate_scor(reference)
	return " ".join(reference[i : i + 4] for i in range(0, len(reference), 4))


# --- Scheme binding ---------------------------------------------------------


def reference_type_for_iban(iban: str, reference: str | None) -> str:
	"""Return the QR-bill reference type (QRR/SCOR/NON) for an IBAN, enforcing
	the binding between account type and reference scheme."""
	if is_qr_iban(iban):
		if not reference:
			raise InvalidReferenceError("A QR-IBAN requires a QRR reference")
		validate_qrr(reference)
		return "QRR"
	if not reference:
		return "NON"
	cleaned = _clean(reference)
	if cleaned.isdigit() and len(cleaned) == QRR_LENGTH:
		raise InvalidReferenceError("A QRR reference requires a QR-IBAN; use SCOR with a normal IBAN")
	validate_scor(reference)
	return "SCOR"
