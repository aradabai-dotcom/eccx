---
name: large-file-decomposition
description: "Turn an oversized file or function into something a reviewer can hold in their head: a 600-line controller, a 400-line function, a module with fifteen responsibilities. Covers measuring what is actually tangled, choosing seams from behaviour rather than line counts, extracting in behaviour-preserving steps, keeping the diff reviewable, and proving nothing changed. Use when a file is too big to review, when one function does everything, when nobody dares touch a module, or before refactoring a legacy hot spot."
metadata:
  origin: eccx-local
---

# Large File Decomposition

Long is not the problem; **tangled** is. A 700-line file with one clear
responsibility reads fine. A 250-line file mixing HTTP, validation, business
rules, and persistence does not. Measure the tangle before moving code.

## When to Activate

- A file exceeds the team's review threshold and reviewers skim it.
- One function has more than ~4 reasons to change.
- A change to one behaviour forces edits in unrelated parts of the same file.
- Tests for this file need a dozen mocks to construct.
- "Nobody touches `billing.js`" is a sentence someone says out loud.

## Step 1 — Measure the tangle, not the length

```bash
# Size and complexity hotspots
cloc src/ --by-file | sort -k5 -n -r | head
npx eslint --rule '{"max-lines-per-function":[1,60],"complexity":[1,12]}' src/

# How many things does this file actually depend on?
grep -c '^import' src/billing.js

# Is it covered? Refactoring without tests is rewriting.
npx jest --coverage --collectCoverageFrom='src/billing.js'
```

If the file has no tests, the first deliverable is a **characterisation test**
that pins current behaviour, including the ugly parts. Do not refactor anything
you cannot prove unchanged.

## Step 2 — Find the seams (behaviour, not line counts)

Split along **change reasons**, not alphabetically and not by "utils".

| Seam type | Signal | Extraction |
|---|---|---|
| I/O boundary | HTTP parsing, DB access, filesystem, clock, randomness | extract and inject |
| Pure logic | pricing, permissions, state transitions, formatting | extract as functions with plain inputs |
| Policy | thresholds, feature flags, rate limits | extract as configuration |
| Error mapping | domain error → HTTP status → message | extract as a table |
| Serialisation | request/response shape | extract as schema or mapper |

A good seam is a place where you can write a test that needs **fewer** mocks
after the extraction than before. If extraction does not reduce mocking in the
tests, you cut in the wrong place.

## Step 3 — Extract in steps that are individually reviewable

```
1. Characterisation tests on the existing behaviour        (no production change)
2. Extract pure functions, called from the original site   (mechanical)
3. Move extracted code to its own module                   (move only, no edits)
4. Replace inline I/O with injected dependencies           (behaviour-preserving)
5. Delete the dead scaffolding left behind                 (cleanup)
```

One commit per step. Never combine a move with a behaviour change: `git blame`
stops being useful and the reviewer cannot verify the move.

## Step 4 — Keep the diff honest

- `git diff -M` so renames and moves are detected rather than shown as
  delete+add.
- Review the moved module on its own before reviewing its call sites.
- If the diff exceeds what a reviewer will read, split by seam into separate PRs.

## Step 5 — Prove nothing changed

- Characterisation tests green before and after, unchanged.
- Public API/route/schema surface identical: snapshot it and diff.
- Behavioural checks on the boundaries: error codes, log shapes, response bodies.
- If there is no test at all, add at least one per branch you touched, plus one
  end-to-end path through the old entry point.

## Anti-patterns

- Splitting by line count ("first 300 lines here") — produces two tangled files.
- Extracting `utils.js` as the destination for everything that did not fit.
- Mixing the move with a rename or a "small improvement"; the reviewer cannot
  tell which lines are behaviour and which are movement.
- Refactoring without characterisation tests, then discovering a behaviour
  change months later in production.
- Splitting a file that only one function ever calls — you traded one problem for
  two files with an indirection.

## Done When

- [ ] The seam list is written down and each seam names a change reason.
- [ ] Characterisation tests existed **before** the first production change.
- [ ] Moves and behaviour changes are in separate commits.
- [ ] Reviewers can read each PR without skimming.
- [ ] The public surface is provably identical (snapshot diff).
