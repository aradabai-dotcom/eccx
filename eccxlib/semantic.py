"""Semantic layer — local sentence embeddings, no network, no service.

Why this file exists: the router is lexical (idf over name/desc/heads). On
queries written by someone who did not read the catalogue, that fails in a way
no amount of weighting fixes — measured, 17 scoring variants moved ±2 points on
94 queries while the answer was often not retrieved at all. The gap is
*vocabulary*: the user describes a situation, the catalogue names a practice.

Measured effect (see docs/ROUTING-GENERALISATION.md):

| set | @1 | @3 | top-50 ceiling |
|---|---|---|---|
| 94 held-out (dev for tuning) | 30.9 → 33.0 | 47.9 → 56.4 | 84.0 → 87.2 |
| 40 sealed (`heldout6`) | 15.0 → 20.0 | 25.0 → 32.5 | 72.5 → 77.5 |

The `@3` gain on the tuning set is 7 wins / 0 losses, McNemar exact p = 0.016.

Design rules, each from a measurement:

  * **Model choice.** `BAAI/bge-small-en-v1.5` via ONNX: 273 MB RSS, 8 ms per
    query, 42 s to embed the whole catalogue once. A cross-encoder was tried
    and **rejected**: `ms-marco-MiniLM-L-6-v2` re-sorted the top 20 and took
    dev@1 from 72 % to 48 %; with a soft fusion it broke even and cost 250 MB
    plus 120 ms per query. It is trained on web passages, not on "short query
    vs component title".
  * **Vectors are built once, at index time**, and stored beside the index. A
    query only embeds itself.
  * **Optional dependency.** `fastembed` is not a hard requirement: without it
    the product is exactly what it was. Nothing here may raise on import.
  * **Staleness is detected, not assumed.** The vector file carries a
    fingerprint of the document set; a catalogue change invalidates it instead
    of silently scoring against the wrong rows.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

MODEL = "BAAI/bge-small-en-v1.5"
DIM = 384
_DEFAULT_STATE = Path(__file__).resolve().parent.parent / ".eccx"
VECTORS = _DEFAULT_STATE / "vectors.npy"
SECTIONS = _DEFAULT_STATE / "sections.npy"
SPANS = _DEFAULT_STATE / "spans.npy"
META = VECTORS.with_suffix(".meta.json")


def use_state(state_dir: Path | None) -> None:
    """Point the vector store at another corpus.

    Rebinding module globals rather than threading a `state=` parameter through
    every helper: there is exactly one active corpus per process, and a
    parameter that defaults to the ECC path is a parameter every caller gets
    wrong once. Called by `cli._index()` when `--corpus` is given, and by the
    tests, which reset it in `tearDown`.
    """
    global VECTORS, SECTIONS, SPANS, META
    base = Path(state_dir) if state_dir else _DEFAULT_STATE
    VECTORS = base / "vectors.npy"
    SECTIONS = base / "sections.npy"
    SPANS = base / "spans.npy"
    META = VECTORS.with_suffix(".meta.json")


def doc_text(doc: dict) -> str:
    """What the model sees for a component.

    Name first, then description: the name is the concept, the description is
    the context. Section headings were tried and dropped — they inflated every
    long document equally and diluted short, precise names.
    """
    return f"{doc['name'].replace('-', ' ')}. {(doc.get('desc') or '').strip()}"[:512]


def fingerprint(docs: list[dict]) -> str:
    h = hashlib.sha256()
    for d in docs:
        h.update(f"{d['kind']}:{d['id']}".encode())
        h.update(b"\0")
    return h.hexdigest()[:16]


def available() -> bool:
    try:
        import fastembed  # noqa: F401
    except Exception:
        return False
    return True


def _model():
    from fastembed import TextEmbedding
    return TextEmbedding(model_name=MODEL, threads=1)


def section_text(doc: dict, section: dict, lines: list[str]) -> str:
    """What the model sees for one H2 section: heading, then the passage."""
    seg = "\n".join(lines[max(0, section["start"] - 1):section["end"]])
    return f"{section.get('h') or ''}. {seg}"[:512].replace("\n", " ")


def build_sections(docs: list[dict]) -> tuple[int, int]:
    """One vector per section, plus the doc index it belongs to.

    4 882 sections for 607 components — 9 minutes of embedding on 2 vCPU, once.
    A component is scored by its **best section**, which is the mechanism: a
    query like "the pod keeps restarting after being killed for memory" has no
    lexical overlap with the description of `kubernetes-patterns`, but a close
    one with its "CrashLoopBackOff" section.
    """
    import numpy as np
    from .util import doc_file, read_text
    model = _model()
    spans, texts = [], []
    for di, doc in enumerate(docs):
        lines = read_text(doc_file(doc)).splitlines()
        for sec in (doc.get("sections") or []):
            seg = "\n".join(lines[max(0, sec["start"] - 1):sec["end"]])
            if len(seg.strip()) < 40:
                continue
            spans.append(di)
            texts.append(section_text(doc, sec, lines))
    S = np.asarray(list(model.embed(texts, batch_size=16)), dtype=np.float32)
    S /= np.maximum(np.linalg.norm(S, axis=1, keepdims=True), 1e-9)
    # Derived, never hard-coded: with `--corpus` the state moves, and a
    # literal path here writes the sections of a user corpus into the ECC
    # checkout. Found the first time `eccx --corpus` was run end to end.
    SECTIONS.parent.mkdir(parents=True, exist_ok=True)
    np.save(SECTIONS, S)
    np.save(SPANS, np.asarray(spans, dtype=np.int32))
    return len(texts), len(docs)


def build_vectors(docs: list[dict], progress=None) -> int:
    """Embed the catalogue once. 42 s for 607 documents on 2 vCPU.

    `batch_size=32` is not tuning: the default (256) was killed by the OOM
    killer on this machine at 1.9 GB. 32 keeps RSS near 520 MB.
    """
    import numpy as np
    model = _model()
    texts = [doc_text(d) for d in docs]
    vecs = np.asarray(list(model.embed(texts, batch_size=32)), dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    vecs /= np.maximum(norms, 1e-9)
    VECTORS.parent.mkdir(parents=True, exist_ok=True)
    np.save(VECTORS, vecs)
    n_sec, _ = build_sections(docs)
    META.write_text(json.dumps({"model": MODEL, "n": len(docs), "dim": int(vecs.shape[1]),
                                "sections": n_sec, "fingerprint": fingerprint(docs)},
                               indent=0))
    return len(docs)


def load_vectors(docs: list[dict]):
    """The document matrix, or None if absent/short/stale. Never raises.

    Kept as the simple accessor used by callers that only need document-level
    similarity (calibration, tests). `load_all()` adds the sections.
    """
    allv = load_all(docs)
    return None if allv is None else allv["docs"]


def load_all(docs: list[dict]):
    """{"docs", "sections", "span"} or None. Staleness is checked once."""
    try:
        import numpy as np
        if not (VECTORS.exists() and META.exists()):
            return None
        meta = json.loads(META.read_text())
        if meta.get("fingerprint") != fingerprint(docs) or meta.get("n") != len(docs):
            return None
        D = np.load(VECTORS)
        if D.shape[0] != len(docs):
            return None
        out = {"docs": D, "sections": None, "span": None}
        if SECTIONS.exists() and SPANS.exists():
            S, span = np.load(SECTIONS), np.load(SPANS)
            if S.shape[0] == span.shape[0] and span.max(initial=0) < len(docs):
                out["sections"], out["span"] = S, span
        return out
    except Exception:
        return None


def embed_query(query: str):
    import numpy as np
    v = np.asarray(list(_model().embed([query], batch_size=1))[0], dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-9)
