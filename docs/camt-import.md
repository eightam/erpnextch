# camt import

Reading a Swiss bank's camt file into ERPNext Bank Transactions.

`erpnextch.camt` parses; `erpnextch.camt.importer` writes. The parser imports
no Frappe and is unit-testable without a site (`erpnextch/camt/tests`).

## What it does, and what it deliberately does not

It produces **clean, de-duplicated Bank Transactions** with the QR reference in
`reference_number` — the field ERPNext's Bank Reconciliation Tool already looks
at — and stops there.

It does **not** match payments to invoices. ERPNext ships the Bank
Reconciliation Tool for that, and a second, worse copy of it is the last thing
this app needs.

The one thing the importer does beyond copying the bank's data: when an
incoming payment carries a QR reference that resolves to exactly one submitted
Sales Invoice, it stamps `party_type`/`party` on the transaction. That is a
lookup of *our own* reference coming back, not a guess, and it earns the
transaction full rank in the reconciliation tool.

## Design decisions worth not re-opening

**Namespace-agnostic parsing.** Every element is matched on its *local* name,
never on a namespace URI. This is not a style preference: Raiffeisen's
transition period for ISO 20022 version 2019 ends on 13 November 2026, and the
element names are identical between `camt.053.001.04` and `.08` — only the
namespace differs. Reading both therefore needs no flag, no configuration and
no migration. Confirmed against a real Raiffeisen export on 2026-08-25, which
is still `.04`.

**Version-tolerant field access.** Where the two versions differ in *shape*
rather than in namespace, both shapes are read: `<Sts>BOOK</Sts>` (2013) and
`<Sts><Cd>BOOK</Cd></Sts>` (2019), `BookgDt/Dt` and `BookgDt/DtTm`.

**All three container shapes** are handled: `BkToCstmrStmt/Stmt` (camt.053),
`BkToCstmrAcctRpt/Rpt` (camt.052), `BkToCstmrDbtCdtNtfctn/Ntfctn` (camt.054).

**Batch bookings are expanded.** A Swiss *Sammelbuchung* arrives as one `Ntry`
with many `TxDtls`, one per paying customer, each carrying its own QR
reference. Booking the sum would throw away exactly the information the
reconciliation needs. Raiffeisen repeats the entry's `AcctSvcrRef` on every
leg, so the legs would de-duplicate against each other — the importer gives
colliding legs distinct ids (`…-1`, `…-2`) instead.

**Pending entries are skipped.** A `PDNG` entry is announced but not booked; it
can still change or disappear, and booking it would put a transaction into the
ledger that the bank has not made.

**Reversals move the money the other way.** `RvslInd=true` on a credit is an
outflow.

**De-duplication is on `transaction_id`**, scoped to the bank account, best
identifier first: `AcctSvcrRef` (the bank's own stable handle), then
`EndToEndId`, then a composite of date, signed amount and reference. Banks
re-deliver statements and accountants import the same file twice; neither may
book a payment twice. Cancelled transactions do not block a re-import —
cancelling one is how a wrong import is undone.

`NOTPROVIDED` is never used as an identifier. Banks write it where the payer
supplied no end-to-end reference; it is not an id.

## Which account a file belongs to

The IBAN the bank reports is the **account IBAN**. It is not necessarily the
IBAN printed on a QR-bill: a **QR-IBAN is a separate number on the same
account**, so a file can legitimately arrive with an IBAN that no `Bank Account`
record carries.

The importer therefore resolves the account by IBAN when it can, and *asks*
when it cannot — a missing match is a question to the user, not an error in the
file. An explicit choice always wins. A file that reports several accounts
cannot be forced onto a single one.

> The rule "a QRR requires a QR-IBAN" (`swiss_qr.reference.reference_type_for_iban`)
> applies when **issuing** an invoice, never when **reading** a payment.
> Enforcing it on import would throw on every real payment, because the bank
> reports the account IBAN while the payment was made to the QR-IBAN.

## Test files

`erpnextch/camt/tests/files/` holds two anonymised files that mirror real bank
exports: a `camt.054.001.04` credit notification (the 2013 shape Raiffeisen
delivers today) and a `camt.053.001.08` statement (the 2019 namespace) carrying
a batch booking, a pending entry, a debit with a SCOR reference, a reversal and
an entry without `TxDtls`.

Every name, address, IBAN and reference in them is a **placeholder**. The IBANs
use IID `99999`, which is not issued to any Swiss bank, so they can never
collide with a real account; their check digits are valid.

**A real export contains payer names and account numbers and must never enter
the repository.**
