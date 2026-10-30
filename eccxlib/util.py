"""Shared helpers for eccx — stdlib only."""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import sys
import time
from pathlib import Path

ADAPTER_ROOT = Path(__file__).resolve().parent.parent
def _default_catalogue() -> Path:
    """Where the catalogue lives when ECC_ROOT is not set.

    The vendored copy under `vendor/ecc/` wins over `~/ECC`: this repository now
    *owns* its catalogue (see vendor/ecc/PROVENANCE.md), so a clone that has
    never seen an upstream checkout must work. Falling back to `~/ECC` keeps
    older setups and the measurement scripts working unchanged.
    """
    vendored = ADAPTER_ROOT / "vendor" / "ecc"
    if (vendored / "skills").is_dir():
        return vendored
    return Path.home() / "ECC"


ECC_ROOT = Path(os.environ.get("ECC_ROOT") or _default_catalogue())
ADAPTER_STATE = ADAPTER_ROOT / ".eccx"

WORD_RE = re.compile(r"[a-z0-9][a-z0-9+#._-]*")
# Function words plus the generic verbs that agents use to phrase any task
# ("make X better", "find where Y", "keep Z in sync"). Left in, they dominate
# scoring: "make" alone ranked `make-interfaces-feel-better` first for a
# refactoring request. These carry no topical signal.
STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "is",
    "are", "be", "this", "that", "it", "as", "at", "by", "from", "use", "using",
    "when", "how", "do", "does", "i", "we", "you", "my", "our", "le", "la", "les",
    "des", "de", "du", "un", "une", "et", "ou", "en", "pour", "avec", "sur", "que",
    "qui", "dans", "au", "aux", "ce", "cette", "je", "tu", "il", "elle", "nous",
    # generic task verbs / determiners
    "make", "made", "get", "got", "let", "keep", "need", "want", "help", "find",
    "give", "take", "put", "set", "start", "started", "stop", "stopped", "look",
    "check", "ensure", "allow", "add", "adds", "added", "create", "creating",
    "write", "writes", "writing", "run", "runs", "running", "fix", "fixing",
    "every", "all", "any", "some", "more", "most", "less", "very", "too",
    "should", "would", "could", "can", "will", "may", "must", "also", "just",
    "then", "than", "there", "here", "where", "what", "which", "who", "why",
    "not", "no", "yes", "if", "so", "but", "about", "into", "over", "under",
    "after", "before", "between", "during", "same", "other", "another",
}


SUFFIXES = ("ings", "ing", "ions", "ion", "ers", "er", "ed", "es", "s")
# Plurals of nouns ending in a sibilant are formed with "-es"; everywhere else
# the plural is "-s" and the "-e" belongs to the root ("service" -> "services").
SIBILANT = ("sses", "xes", "zes", "ches", "shes")
# Words whose final "-e" is silent, so the plural is spelled "-es" but the root
# is the full word. Without this, "cache" stems to "cache" while "caches" stems
# to "cach" and the two never match. Lexicon, not linguistics: apply sparingly.
STEM_EXCEPTIONS = {"cache": "cach"}


def _stem_once(word: str) -> str:
    if len(word) < 5:
        return word
    if word.endswith(("ss", "us", "is")):
        return word
    if word.endswith("ies") and len(word) - 3 >= 4:
        return word[:-3] + "y"  # repositories -> repository
    for suf in SUFFIXES:
        if not word.endswith(suf) or len(word) - len(suf) < 4:
            continue
        if suf == "es" and not word.endswith(SIBILANT):
            return word[:-1]  # services -> service, not servic
        base = word[: -len(suf)]
        if suf in ("ing", "ings", "ed") and len(base) >= 3 and base[-1] == base[-2]:
            base = base[:-1]  # 'debugging' -> 'debugg' -> 'debug'
        return base
    return word


def stem(word: str) -> str:
    """Very light morphological stemmer (English-biased, conservative).

    ECC names are hyphenated noun phrases: 'onboarding' must match 'onboard',
    'hooks' must match 'hook', 'repositories' must match 'repository'. We only
    strip when at least 4 chars survive, and we stem to a *fixpoint*: a single
    pass made 'filtering' -> 'filter' while 'filter' -> 'filt', so a derived
    form and its root never matched. Iterating costs microseconds and makes
    the relation consistent.

    Known limits (pinned by tests, not accidents): '-ation' nouns keep their
    suffix ('verification' vs 'verify'), and '-er' is stripped from lexical
    roots ('matter' -> 'matt'). Both are consistent on both sides of the
    match, so they cost order, not recall.
    """
    if word in STEM_EXCEPTIONS:
        return STEM_EXCEPTIONS[word]
    for _ in range(4):
        nxt = _stem_once(word)
        if nxt == word:
            break
        word = nxt
    return word


def tokenize(text: str) -> list[str]:
    """Lowercase word tokens, hyphen/dot split into parts as well as whole."""
    out: list[str] = []
    for raw in WORD_RE.findall(text.lower()):
        if len(raw) < 2:
            continue
        if raw in STOP:
            continue
        out.append(stem(raw))
        if any(sep in raw for sep in "-._+/"):
            for part in re.split(r"[-._+/]", raw):
                if len(part) >= 2 and part not in STOP:
                    part = stem(part)
                    if part != stem(raw):
                        out.append(part)
    return out


def est_tokens(text: str) -> int:
    return max(1, round(len(text) / 4))


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def load_json(path: Path, default):
    try:
        return json.loads(read_text(path))
    except Exception:
        return default


def save_json(path: Path, data, indent: int | None = None) -> None:
    """Write JSON atomically: temp file in the same directory, then rename.

    `Path.replace` is atomic on POSIX, so a reader either sees the whole old
    file or the whole new one — never a truncated one. The temp name is unique
    per process, because two `eccx` invocations writing `x.json.tmp` at the
    same time corrupt each other's temp file and *then* rename garbage into
    place.

    `indent` exists so a human can still read `rerank-cache.json` while
    debugging; the atomicity does not depend on it.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(data, ensure_ascii=False, indent=indent)
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())   # a rename without fsync can survive as a
                                    # zero-length file after a power loss
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


@contextlib.contextmanager
def locked(path: Path, timeout: float = 10.0):
    """Exclusive lock around a read-modify-write of `path`.

    Every writer here does load -> mutate -> save. Two of them running at once
    (an agent applying two rerank judgements, a hook and a command) each read
    the same snapshot and the second save silently erases the first. Measured:
    10 writes from 2 processes left 5 on disk.

    `flock` on a sidecar file, not on the data file: the data file is replaced
    by rename, so a lock held on its old inode would not exclude anything.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() > deadline:
                    raise TimeoutError(f"lock busy for {timeout}s: {lock_path}") from None
                time.sleep(0.02)
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def c(text: str, color: str) -> str:
    if not sys.stdout.isatty() or os.environ.get("NO_COLOR"):
        return text
    codes = {"dim": "2", "b": "1", "g": "32", "y": "33", "r": "31", "c": "36"}
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


def hr(title: str = "") -> str:
    if not title:
        return "-" * 72
    pad = max(0, 70 - len(title))
    return f"--- {title} " + "-" * pad


TRUNC_MARK = "\n[... truncated by eccx budget ...]"


def truncate(text: str, max_chars: int) -> str:
    """Cut to *at most* max_chars, marker included.

    The marker used to be appended after cutting, so the result was
    max_chars + 33 and every caller's budget was quietly exceeded — and a
    second call truncated the marker itself, so truncate was not idempotent.
    Both are contract violations for a function named after a budget.
    """
    if len(text) <= max_chars:
        return text
    if max_chars <= len(TRUNC_MARK):
        # A budget smaller than the marker itself: honouring the budget wins
        # over announcing the cut. (Before, the marker was always appended, so
        # truncate(x, 10) returned 35 chars.)
        return text[:max_chars]
    room = max_chars - len(TRUNC_MARK)
    cut = text[:room]
    nl = cut.rfind("\n")
    if nl > room * 0.6:
        cut = cut[:nl]
    return cut.rstrip() + TRUNC_MARK


def doc_file(doc: dict) -> Path:
    """Where an indexed document actually lives.

    Local overlay skills are stored with `path` relative to the *adapter* root,
    not to the ECC clone. Every reader used to do `ECC_ROOT / doc["path"]`,
    which resolves to a file that does not exist — so the three skills that
    close the catalogue gaps could be routed to but their body was always
    empty. Routing metrics (which only compare ids) could not see it.
    """
    extra = doc.get("extra") or {}
    if extra.get("root") == "corpus":
        # An indexed directory the user owns. `path` is relative to it.
        return Path(extra["corpus"]) / doc["path"]
    root = ADAPTER_ROOT if extra.get("root") == "adapter" else ECC_ROOT
    return root / doc["path"]


def die(msg: str, code: int = 1):
    print(msg, file=sys.stderr)
    raise SystemExit(code)


def ensure_ecc_deps(quiet: bool = False) -> bool:
    """Re-install ECC's npm deps if the sandbox dropped them.

    Workspace snapshots exclude `node_modules`, so a fresh session can have the
    ECC clone but no deps. Everything that shells out to ECC's node CLI (memory
    vault, installer) calls this first; it is a ~3s no-op when deps are present.
    """
    import shutil
    import subprocess

    nm = ECC_ROOT / "node_modules"
    if nm.is_dir():
        return True
    if not (ECC_ROOT / "package.json").is_file():
        return False
    npm = shutil.which("npm")
    if not npm:
        return False
    if not quiet:
        print("[eccx] ECC node_modules missing (snapshot-excluded) — reinstalling…",
              file=sys.stderr)
    try:
        p = subprocess.run(
            [npm, "install", "--ignore-scripts", "--no-audit", "--no-fund",
             "--loglevel=error"],
            cwd=str(ECC_ROOT), capture_output=True, text=True, timeout=300)
        ok = p.returncode == 0
    except Exception:
        return False
    # npm rewrites upstream's `yarn.lock` (the repo pins packageManager
    # yarn@4.9.2) and the workspace snapshot drops file modes, so every
    # executable in the clone comes back as 0644. Left alone, each reinstall
    # and each restart dirties the clone, and `git status` stops being the
    # proof that upstream is untouched — which is the invariant this whole
    # adapter rests on. `core.fileMode=false` fixes the mode half at the
    # source; the yarn.lock half needs a restore because it is a real content
    # change npm makes on purpose.
    try:
        subprocess.run(["git", "-C", str(ECC_ROOT), "config", "core.fileMode", "false"],
                       capture_output=True, text=True, timeout=30)
        st = subprocess.run(["git", "-C", str(ECC_ROOT), "status", "--porcelain",
                             "--", "yarn.lock"],
                            capture_output=True, text=True, timeout=30)
        if st.stdout.strip():
            subprocess.run(["git", "-C", str(ECC_ROOT), "checkout", "--", "yarn.lock"],
                           capture_output=True, text=True, timeout=30)
            if not quiet:
                print("[eccx] npm rewrote yarn.lock — restored from git "
                      "(upstream stays byte-identical)", file=sys.stderr)
    except Exception:
        pass
    return ok
