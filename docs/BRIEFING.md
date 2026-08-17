# PINTO / erpnextCH — Agent Briefing

## 1. What we are building

Two repos, deliberately separated:

| Repo | Package | Purpose | License |
|---|---|---|---|
| `eightam/erpnextCH` | `erpnextch` | Generic Swiss localisation for ERPNext v16. **No client logic.** Reusable across projects. | GPL-3.0 |
| `eightam/pinto_erp` | `pinto` | Client-specific: dealer pricing, Lobster dispatch, warranty, portal API. | proprietary |

The split is the point. `erpnextch` is an asset we carry to the next Swiss
ERPNext client. Anything that would only ever make sense for one customer does
not belong in it.

**Client:** Rad 9, Rorschach — bicycle brand **PINTO**. ~100 frames/year,
12 frame SKUs, single warehouse, B2B dealer portal + warranty registration.

**Naming:** the project was formerly called "Camino". That name is dead for
trademark reasons. The string `camino` must not appear anywhere — code,
comments, test data, print formats, commit messages.

---

## 2. Stack

- ERPNext **v16.32.1**, Frappe v16. Track `version-16` at build time.
- **Pin an image digest in `compose.prod.yaml`.** Never `:latest` in production —
  a 3 a.m. container restart must not pull untested code into bookkeeping.
- Trader portal: Next.js BFF against the ERPNext REST API.
- Deployment: Docker Compose. Dokploy on prod only (see §6).

### Explicitly rejected: `libracore/erpnextswiss`

Decided in ADR-001. Reasons, so nobody re-opens it:

1. It covers ~40 feature areas (payroll, ESR, EBICS, ZUGFeRD, EDI, DPD, Mautic…).
   We need four. Every ERPNext minor would mean regression-checking all forty.
2. It is **AGPL-3.0**. § 13 bites on network interaction, and a trader portal is
   exactly that. Copying its code would make `erpnextch` permanently AGPL and
   destroy its reuse value.
3. Its documented compatibility branches stop at v15.

**Read it for reference if useful. Never copy code from it.** The public
specification (paymentstandards.ch, ISO 20022) is the better source anyway.

`alyf-de/erpnext_germany` (GPL-3.0, active `version-16` branch) is the
**structural** template: hooks.py patterns, fixture layout, CI, packaging.
Copy the skeleton, not the content — DATEV/XRechnung are irrelevant here.

---

## 3. Scope of `erpnextch`

Build these four, extensibly. Nothing else for now.

### 3.1 QR-bill (Swiss QR-Rechnung)

- Use the **`qrbill`** PyPI package (MIT, v1.2.0) to render the *Zahlteil*. Do
  not draw it by hand — the spec pins geometry to the millimetre (105×210 mm
  payment part, 46×46 mm QR, 7×7 mm Swiss cross, perforation, font sizes).
- **We own the payload and its validation.** Keep it in a module with no Frappe
  import so it is unit-testable without a site.
- Payload is `SPC` / `0200` / `1`, then a strictly ordered, CRLF-separated field
  list (creditor block 7 lines, ultimate creditor 7 empty lines, amount,
  currency, debtor block 7 lines, reference type, reference, unstructured
  message, `EPD` trailer, bill information).
- **Reference scheme is bound to the account type — enforce it:**
  - QR-IBAN (IID in positions 5–9 within **30000–31999**) → **QRR mandatory**
    (27 digits, *Modulo 10 rekursiv* check digit).
  - Normal IBAN → **SCOR** (ISO 11649, `RF` + 2 check digits) or no reference.
    A QRR with a normal IBAN is rejected by the bank.
- Mod-10-recursive table and a known-good test vector:
  `21000000000313947143000901` → check digit **7**
  (full reference `210000000003139471430009017`). Put this in a unit test.
- SCOR check: `98 - mod97(payload + "RF00")`, letters as A=10…Z=35.
  Test vector: payload `539007547034` → `RF18539007547034`.
- Print formats DE and FR. IT/EN optional.

### 3.2 camt.052 / 053 / 054 import

- **Parse namespace-agnostically, matching on local element names.** This is not
  a style preference: Raiffeisen's transition period for **ISO 20022 version
  2019** ends **13 November 2026** — inside the go-live window. The element
  names are identical between `camt.053.001.04` and `.08`; only the namespace
  differs. Namespace-agnostic parsing reads both with no flag and no migration.
- Handle all three container shapes: `BkToCstmrStmt/Stmt`,
  `BkToCstmrAcctRpt/Rpt`, `BkToCstmrDbtCdtNtfctn/Ntfctn`.
- Expand batch bookings (*Sammelbuchungen*, multiple `TxDtls` per `Ntry`) into
  individual transactions — each leg carries its own reference.
- The reconciliation key is `RmtInf/Strd/CdtrRefInf/Ref` → ERPNext
  `Bank Transaction.reference_number`. That is our own QRR coming back, so
  matching is a direct lookup, not fuzzy.
- De-duplicate on `AcctSvcrRef` (fall back to `EndToEndId`, then a composite of
  date + signed amount + reference) in `transaction_id`.
- Skip `PDNG` (pending) entries by default — they are not booked yet.
- **Do not reimplement matching.** ERPNext core's Bank Reconciliation Tool does
  it. We only produce clean Bank Transactions.

### 3.3 Kontenrahmen KMU

- ERPNext core ships **no** Swiss chart of accounts — verify, then ship ours.
- Core does not discover CoA JSON from other apps. Use
  `erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts.create_charts()`
  with the `custom_chart` parameter from a setup function, rather than trying to
  get it into the Company dropdown.
- Standard KMU structure: 1 Aktiven, 2 Passiven, 3 Betriebsertrag, 4 Material-
  und Warenaufwand, 5 Personalaufwand, 6 sonstiger Betriebsaufwand,
  7 betriebliche Nebenerfolge, 8 ausserordentlicher Erfolg/Steuern, 9 Abschluss.
- **This needs Treuhänder sign-off.** Ship it as a starting point, flag it as
  such in the README, do not present it as authoritative.

### 3.4 MwSt

- Tax templates: **8.1 %** standard, 2.6 % reduced, 3.8 % accommodation, 0 %.
- **No easyTax / ePortal export.** Decided: the Treuhänder gets an account
  statement plus balances. Do not build the electronic filing path.
- Leave the seam open so a later `erpnextch.vat.export` module can be added
  without restructuring.

### Out of scope (do not build)
ESR (dead since 30.09.2022), pain.001/pain.008, EBICS, ZUGFeRD, payroll /
Lohnausweis / SECO, Zefix, any payment or logistics connector.
**Dunning is ERPNext core** — do not rebuild it.

---

## 4. Non-negotiable working rules

1. **Never configure in the ERPNext Desk UI.** If a setting does not exist as a
   fixture or a patch in the app, it does not exist. Config is code.
2. **`make reset` must always work** — wipe the site, rebuild from git, reseed.
   That is both the disaster-recovery test and the proof that rule 1 holds.
3. **Run `make verify` after every change** and report the actual result. Never
   report "should work" without a green run. Verify covers: migrate,
   fixture-drift check, `camino` naming grep, pytest, Playwright.
4. **Never touch production.** No SSH, no Dokploy API, no prod database.
   Nick clicks production deploys.
5. **No real secrets.** Only `.env.example` and anonymised
   `fixtures-sample/`. Real keys live in Dokploy's env store.
6. **Do not patch ERPNext core.** Use hooks, `override_doctype_class`,
   `doc_events`, Custom Fields.
7. **Ask, do not guess** on: a new DocType, a new field on a core DocType, any
   change to the booking flow, anything touching bank / QR / camt, or a
   deviation from the design.

### Swiss conventions
CHF · dates `TT.MM.JJJJ` · language `de-CH`, print formats also `fr-CH` ·
GeBüV: submitted documents are immutable, 10-year retention.

---

## 5. Definition of done for the first milestone

**A real Swiss QR-bill, generated from a real Sales Order, that scans in a
banking app.**

1. ERPNext v16.32.1 running on the staging box via Docker Compose.
2. `erpnextch` installed; Kontenrahmen KMU and MwSt templates applied.
3. One company, one dealer customer with a dealer price list, two frame item
   templates with Color/Size variants (12 SKUs).
4. Sales Order → Delivery Note → Sales Invoice with a rendered QR-bill PDF.
5. The PDF lands in `artifacts/` for Nick to scan with a banking app — this is
   the one test the agent cannot perform itself.
6. `make verify` green.

---

## 6. Environment

- **Staging: one VPS, no Dokploy.** Plain Docker + Compose + Caddy for TLS.
  Dokploy would own the compose lifecycle and its own checkout, which fights a
  fast local iteration loop. Staging is shell-driven and agent-owned.
- **Production: added later**, fresh from the repo at the first real camt file —
  never by repurposing the staging box. Dokploy there, UI-driven, human-owned.
- The agent runs on the staging box itself, in `tmux`, via
  `claude remote-control` so Nick can steer it from mobile.

---

## 7. Open questions — ask, do not assume

1. Kontenrahmen KMU: which exact variant does the Treuhänder want?
2. Lobster interface contract (format, transport, acknowledgements) — not yet
   agreed with the logistics company. Do not design against a guess.
3. Rad 9's Raiffeisen account: is it already migrated to ISO 20022 version 2019,
   and is the IBAN a QR-IBAN? Both change behaviour. Real camt sample files are
   needed before the import path can be called done.
4. Serial number scheme for frames (drives warranty registration).
