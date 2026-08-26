# erpnextch

Swiss localisation for ERPNext v16. Four feature areas, deliberately nothing
more:

- **QR-bill** (Swiss QR-Rechnung): payload building and validation in pure
  Python (`erpnextch.swiss_qr`, no Frappe imports, unit-testable without a
  site); rendering of the payment part via the [`qrbill`](https://pypi.org/project/qrbill/)
  package. QRR references are enforced for QR-IBANs, SCOR (ISO 11649) for
  normal IBANs.
- **camt.052/053/054 import**: namespace-agnostic parsing (`erpnextch.camt`,
  no Frappe imports) into ERPNext Bank Transactions (`erpnextch.camt.importer`).
  Reads the ISO 20022 versions 2013 and 2019 without a flag, expands batch
  bookings into their legs, skips pending entries and de-duplicates on the
  bank's own reference, so re-importing a file books nothing twice. Matching
  itself is left to ERPNext core's Bank Reconciliation Tool — see
  `docs/camt-import.md`.
- **Kontenrahmen KMU**: a Swiss SME chart of accounts, applied via a setup
  function. **This is a starting point, not an authoritative chart** — have
  your fiduciary (Treuhänder) review and adapt it before going live.
- **MwSt**: Swiss VAT templates (8.1 % standard, 2.6 % reduced, 3.8 %
  accommodation, 0 %). No electronic filing/export path.

Out of scope by design: ESR, pain.001/pain.008, EBICS, ZUGFeRD, payroll,
dunning (ERPNext core has it), payment/logistics connectors.

## License

GPL-3.0 — see `LICENSE`.
