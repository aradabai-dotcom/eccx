---
name: repository-hygiene
description: "Diagnose and fix a bloated or slow repository: multi-gigabyte clones, committed binaries and build output, history that cannot be shallow-cloned, enormous working trees, and checkout times that waste every session. Covers measuring where the weight actually is, deciding between rewriting history versus quarantine, using git filter-repo and LFS correctly, and preventing regrowth with hooks and CI budgets. Use when a clone takes minutes, when the repo is several GB, when checkouts are slow, or before open-sourcing a large private repository."
metadata:
  origin: eccx-local
---

# Repository Hygiene

A slow repository is a tax every engineer and every agent pays on every session.
Measure first: the weight is almost never where people assume.

## When to Activate

- `git clone` takes minutes, or the `.git` directory is hundreds of MB or more.
- Checkout or `git status` is slow on a machine that is otherwise fine.
- Build artefacts, databases, videos, model weights, or vendored dependencies
  have been committed.
- Before open-sourcing, transferring ownership, or adding CI that clones often.

## Step 1 — Measure, do not guess

```bash
# Size of history vs working tree
du -sh .git
git count-objects -vH

# What is big in the current tree
git ls-tree -r -l HEAD | sort -k4 -n -r | head -20

# What is big across all history (the real cost)
git rev-list --objects --all \
  | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' \
  | awk '$1=="blob"{print $3, $4}' | sort -n -r | head -25

# Who made it big
git verify-pack -v .git/objects/pack/*.idx | sort -k3 -n | tail -10
```

Record before/after numbers. A hygiene task without a measurement is a rumour.

## Step 2 — Classify the weight

| Category | Typical culprit | Fix |
|---|---|---|
| Build output | `dist/`, `target/`, `.next/`, `node_modules` | remove from index, add to `.gitignore` |
| Media | videos, design exports, screenshots | Git LFS, or an asset store |
| Data | CSVs, fixtures, SQL dumps, model weights | LFS, or generated-on-demand |
| Vendored code | third-party source trees | package manager |
| Deleted-but-remembered | a 900 MB file deleted two years ago | history rewrite |

Deleting a file does **not** shrink the clone: the blob stays in history.
That distinction is the whole reason this skill exists.

## Step 3 — Choose the intervention

**Ignore forward only** (safe, cheap): remove from the index, add to
`.gitignore`. Clone size does not shrink. Right when the weight is recent and
tolerable.

**Quarantine to LFS** (moderate): `git lfs migrate import --include="*.psd"`.
Rewrites history for those paths; every collaborator must re-clone.

**Rewrite history** (last resort, irreversible in practice):

```bash
# Backup first — this is not recoverable from the remote alone
git clone --mirror repo repo-backup.git

pip install git-filter-repo
git filter-repo --invert-paths --path path/to/big.bin
git filter-repo --strip-blobs-bigger-than 5M
```

Then: force-push, rotate every collaborator's working copy, and treat every open
PR as needing a rebase. Announce the window; a silent force-push costs a day.

**Shallow / partial clones** (no rewrite): if the goal is fast CI rather than a
small repo, `git clone --depth 1` or `--filter=blob:none` may be enough. This is
usually the cheapest win and is often overlooked.

## Step 4 — Prevent regrowth

- `.gitignore` entries plus a **pre-commit check** for files over a size budget.
- CI budget check: fail if `.git` grows beyond a threshold between releases.
- A `CODEOWNERS` rule for large-asset directories.
- Document the storage decision: assets belong in the asset store, not in git.

## Anti-patterns

- `git rm -r --cached . && git add .` as a cleanup strategy — it changes the
  index, not the history, and often commits the same junk under new names.
- Rewriting history on a shared branch without a freeze window.
- Adding LFS for files that are generated and should not be stored at all.
- "Deleting" big files and concluding the clone is fixed.

## Done When

- [ ] Before/after measured: `.git` size, clone time, checkout time.
- [ ] Every category in the table has a documented decision.
- [ ] `.gitignore` and a size-budget check prevent the same file returning.
- [ ] If history was rewritten: backups exist, window communicated, mirrors updated.
- [ ] Assets that do not belong in git live somewhere with a retention policy.
