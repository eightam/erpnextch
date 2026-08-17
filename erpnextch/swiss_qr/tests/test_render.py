"""Cross-check: the payload we own must be exactly what qrbill encodes into
the QR code. Skipped where qrbill is not installed (host runs); runs in the
bench venv via `make pytest`."""

import pytest

qrbill = pytest.importorskip("qrbill")

from erpnextch.swiss_qr.payload import Party, QRBillData
from erpnextch.swiss_qr.render import build_qrbill, render_svg


def make_bill():
	return QRBillData(
		account="CH4431999123000889012",
		creditor=Party(
			name="Rad9 GmbH",
			street="Tödistrasse",
			building_number="9",
			postal_code="9400",
			town="Rorschach",
		),
		amount=3545.70,
		debtor=Party(
			name="Velo Muster AG",
			street="Bahnhofstrasse",
			building_number="1",
			postal_code="8000",
			town="Zürich",
		),
		reference="210000000003139471430009017",
		message="ACC-SINV-2026-00001",
	)


def test_payload_matches_qrbill_qr_data():
	data = make_bill()
	bill = build_qrbill(data, language="de")
	assert bill.qr_data() == data.payload()


def test_svg_renders():
	svg = render_svg(make_bill(), language="de")
	assert svg.startswith("<?xml") or svg.startswith("<svg")
	assert "svg" in svg[:200]
