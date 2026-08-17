# erpnextch — working rules

Generic Swiss localisation for ERPNext v16. GPL-3.0, intended to be published
and reused. **No client-specific logic** — anything that only makes sense for
one customer belongs in `pinto_erp`, not here.

Authoritative context: `docs/BRIEFING.md`. Read it first.

## Non-negotiable working rules

1. **Never configure in the ERPNext Desk UI.** If a setting does not exist as a
   fixture or a patch in the app, it does not exist. Config is code.
2. **`make reset` must always work** — wipe the site, rebuild from git, reseed.
   That is both the disaster-recovery test and the proof that rule 1 holds.
3. **Run `make verify` after every change** (from `pinto_erp/`) and report the
   actual result. Never report "should work" without a green run. Verify
   covers: migrate, fixture-drift check, banned-name grep, pytest,
   Playwright.
4. **Never touch production.** No SSH, no Dokploy API, no prod database.
5. **No real secrets.** Only `.env.example` and anonymised `fixtures-sample/`.
6. **Do not patch ERPNext core.** Use hooks, `override_doctype_class`,
   `doc_events`, Custom Fields.
7. **Ask, do not guess** on: a new DocType, a new field on a core DocType, any
   change to the booking flow, anything touching bank / QR / camt, or a
   deviation from the design.

## Repo-specific rules

- Payload building and validation (QR reference, camt parsing) live in modules
  with **no Frappe import**, unit-testable without a site.
- QR rendering goes through the `qrbill` PyPI package — never draw the payment
  part by hand.
- Never copy code from `libracore/erpnextswiss` (AGPL; ADR-001). Reference
  reading only. The public spec (paymentstandards.ch, ISO 20022) is the source.
- Structural template is `alyf-de/erpnext_germany` (`version-16` branch):
  hooks.py patterns, fixture layout, packaging. Skeleton, not content.
- The dead former project name (BRIEFING.md §1) must not appear anywhere: code,
  comments, test data, print formats, commit messages.
- Swiss conventions: CHF, dates `TT.MM.JJJJ`, language `de-CH`, print formats
  also `fr-CH`. GeBüV: submitted documents are immutable, 10-year retention.
