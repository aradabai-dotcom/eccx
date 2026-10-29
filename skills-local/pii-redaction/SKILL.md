---
name: pii-redaction
description: "Detect and remove personal and sensitive data before it reaches a model provider, a log sink, or a third-party tool. Covers what counts as PII (names, emails, phones, addresses, account and card numbers, IPs, free-form identifiers), where it leaks (prompts, tool arguments, retrieved documents, telemetry, error reports), deterministic redaction with format-preserving tokens, reversible vaulting when the original is still needed, and the tests that prove nothing slipped through. Use when sending user content to an external model, building an agent that reads customer data, redacting logs or traces, or when a response has quoted back data the user did not intend to share."
metadata:
  origin: eccx-local
---

# PII Redaction

A model provider is a third-party recipient of everything you paste into a
prompt. Treat user content the same way you would treat data sent to any vendor:
the minimum necessary, redacted where it is not needed, verifiable after the fact.

## When to Activate

- Content from real users is about to leave your trust boundary (prompt, tool
  argument, retrieval context, embedding, telemetry, crash report).
- An assistant echoed back a real name, address, or identifier.
- Building or reviewing an agent that reads mailboxes, tickets, CRM records,
  support transcripts, invoices, or medical data.
- Writing log statements, traces, or error handlers around user objects.

## Threat Model — write it down before writing regexes

For each data flow, answer three questions:

1. **Who receives it?** (model provider, log aggregator, analytics, another team)
2. **Is the data necessary?** If the task is "classify this ticket", the email
   address is almost never needed.
3. **Can it be reversed?** A caller who needs the real value later requires a
   token-to-value vault with an audit trail, not a one-way hash.

## Classification

| Class | Examples | Default treatment |
|---|---|---|
| Direct identifier | name, email, phone, postal address, national ID | replace with typed token |
| Account data | card PAN, IBAN, account number, customer ID | replace, or last-4 only if the task needs matching |
| Network identifier | IP, MAC, device ID, session cookie | truncate or replace |
| Special category | health, biometric, religion, sexual orientation, trade-union, political opinion | do not send; require explicit legal basis |
| Quasi-identifier | DOB, postal code, job title, salary band | generalise (year, region, band) |
| Free-form risk | "my son's school, St Mary's, called…" | needs NER + human review, regex will miss it |

## What to Do

1. **Redact at the boundary, not at the call site.** One choke point that every
   outbound payload passes through. Two call sites means two places to forget.
2. **Prefer allow-listing to block-listing.** Build the outbound object from
   known-safe fields instead of serialising a user record and stripping it.
3. **Use typed tokens.** `<EMAIL_1>`, `<PHONE_1>` keep the shape of the data
   (so the model can still reason "two different emails") without the value.
   Stable per conversation, so coreference still works.
4. **Never log the raw value "for debugging".** If you must, gate it behind an
   explicit break-glass flag that is off in production and audited in review.
5. **Redact before the retriever, not only before the prompt.** Documents pulled
   into context are the most common leak path.

## Detection — pragmatic ladder

```
1. Structural fields      typed columns, schema-validated inputs   → always reliable
2. Format-anchored regex  email, phone (E.164), IBAN, card (Luhn)  → good recall
3. Entity recognition     names, addresses, orgs                   → good recall, false positives
4. Human review           free-form narrative                      → required for special category
```

Regex alone is not a redaction strategy; it is the floor. Validate a card number
with Luhn before you call it a card number, or you will mangle order IDs.

## Verification — the part that is usually skipped

- **Fixture corpus.** A file of realistic records, including edge cases
  (unicode names, numbers with spaces, addresses split across fields).
- **Assertion style.** Assert on the *absence* of the raw values in the outbound
  payload, not the presence of tokens. Missing values fail loudly.
- **Leak test in CI.** Serialise a sample user into every outbound path
  (prompt, log, trace, error) and fail the build if any known token appears.
- **Regression on incident.** When something leaks, add the exact shape to the
  corpus before fixing the pattern.

## Reversible vaulting

When the caller needs the real value after the model responds:

1. Replace value with `TOKEN_n`, store `{TOKEN_n: value}` in a short-lived store
   keyed by conversation, never in the prompt.
2. Model returns text containing `TOKEN_n`.
3. Rehydrate server-side, after the response leaves the provider.
4. Expire the vault aggressively; log access counts, never contents.

## Anti-patterns

- Hashing an email "to be safe" and calling it done — it is linkable and often
  reversible by dictionary attack.
- Redacting the prompt but not the tool arguments the model emits.
- Redacting production logs but shipping the same object to Sentry.
- One regex for "all PII", maintained by nobody.
- Silent failure: if redaction errors, the request must be blocked, not sent raw.

## Done When

- [ ] Every outbound path has exactly one redaction choke point.
- [ ] Classified table exists for the data the system actually handles.
- [ ] Leak test in CI fails on a raw value in any outbound payload.
- [ ] Break-glass path is opt-in, off by default, and logged.
- [ ] Special-category data is refused by design, not filtered by regex.
