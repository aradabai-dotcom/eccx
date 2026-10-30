"""eccx — ECC adapted to a harness-less sandbox agent.

Subcommands mirror what a real harness does for ECC:
  recall   route a task to skills/agents/commands under a token budget
  show     read one component in full
  cmd      render a slash-command with $ARGUMENTS substituted
  agent    assemble an agent brief (+ routed skills) for delegation
  rules    emit the rule pack that matches a project
  fire     run the ECC hook graph for an event (Claude Code contract)
  tools    list/probe MCP servers
  mcp      call an MCP tool over stdio
  session  durable memory (init/save/search/read)
  bootstrap write an agent brief into a project
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

from . import frontmatter as fm
from . import hooks, indexer, memory, router
from .util import (ADAPTER_STATE, ADAPTER_ROOT, ECC_ROOT, c, die, doc_file,
                   est_tokens, read_text, truncate)


# --------------------------------------------------------------------- utils

def _package_version() -> str:
    """The version that was installed, not one written down twice.

    `eccx --version` did not exist until a wheel was installed in a clean venv
    and asked for it — the only way to tell which build is running.
    """
    try:
        from importlib.metadata import version
        return version("eccx")
    except Exception:
        return "0.0.0+unknown"


def _corpus_root(args=None) -> "Path | None":
    raw = getattr(args, "corpus", None) if args is not None else None
    return Path(raw).expanduser().resolve() if raw else None


def _unreadable_routes(results: list[dict]) -> list:
    """Routes whose source file is gone.

    `read_text` returns "" on OSError, so a deleted catalogue and an empty
    document render identically: `## Content` followed by nothing. Measured on
    a wheel with `ECC_ROOT` moved away and an index already built, recall
    returned 1 222 bytes against 4 963 — the routes survived, every body
    vanished, and nothing on stderr said so. Silence here is the worst outcome
    available: the agent gets a list of filenames it cannot open.
    """
    from .util import doc_file
    return [p for p in (doc_file(r["doc"]) for r in results) if not Path(p).is_file()]


def _source(args=None) -> tuple[str, str]:
    """Name the thing being searched, truthfully.

    eccx has two modes and only one of them involves ECC. In `--corpus` mode the
    reader is searching their own folder: printing "ECC context" there tells them
    a dependency was used when none was, and hides the fact that the tool works
    standalone. Found by running the wheel in a venv with no ECC on disk.
    """
    if _corpus_root(args) is not None:
        return "corpus", "document"
    return "ECC", "ECC component"


def _use_corpus_state(root) -> None:
    """Every corpus keeps its own index and vectors under ~/.eccx/<slug>/.

    `~/.eccx` and not the corpus itself: indexing must never write into the
    folder a user is editing (and often syncing, or under git).
    """
    from . import semantic
    if root is None:
        semantic.use_state(None)
        _STATE_OVERRIDE["dir"] = None
        return
    state = _state_dir(root)
    semantic.use_state(state)
    _STATE_OVERRIDE["dir"] = state


_STATE_OVERRIDE: dict = {"dir": None}


def _state_dir(root) -> "Path":
    name = re.sub(r"[^a-z0-9]+", "-", str(Path(root)).lower()).strip("-")[-40:]
    return Path.home() / ".eccx" / name


def _index(args=None):
    root = _corpus_root(args)
    if root is None:
        return indexer.load()
    from . import corpus
    state = _state_dir(root)
    if not (state / "index.json").exists():
        die(f"no corpus index for {root}\n  eccx corpus build --dir {root}")
    idx = corpus.load_from(state)
    if corpus.is_stale(idx):
        print(f"# corpus changed since the build — rebuild with: "
              f"eccx corpus build --dir {idx['root']}", file=sys.stderr)
    return idx


def _find(index: dict, spec: str) -> dict | None:
    """Resolve 'skill:name', 'name', or a unique substring to one doc."""
    docs = index["docs"]
    if ":" in spec:
        kind, _, cid = spec.partition(":")
        for d in docs:
            if d["kind"] == kind and d["id"].lower() == cid.lower():
                return d
    low = spec.lower()
    exact = [d for d in docs if d["id"].lower() == low or d["name"].lower() == low]
    if len(exact) == 1:
        return exact[0]
    partial = [d for d in docs if low in d["id"].lower()]
    if len(partial) == 1:
        return partial[0]
    if partial:
        print(f"'{spec}' is ambiguous:", file=sys.stderr)
        for d in partial[:12]:
            print(f"  {d['kind']}:{d['id']}", file=sys.stderr)
        return None
    print(f"No ECC component matches '{spec}'. Try `eccx search <words>`.", file=sys.stderr)
    return None


def _project(args) -> Path:
    return Path(getattr(args, "project", None) or os.getcwd()).resolve()


def _context_for(project: Path) -> list[str]:
    return router.detect_packs(project) if project.is_dir() else []


# ---------------------------------------------------------------- subcommands

def cmd_init(args) -> int:
    project = _project(args)
    idx = indexer.build()
    st = indexer.stats(idx)
    msg = memory.init(project)
    ADAPTER_STATE.mkdir(parents=True, exist_ok=True)
    save = ADAPTER_STATE / "config.json"
    save.write_text(json.dumps({"project": str(project), "at": time.time(),
                                "ecc_root": str(ECC_ROOT)}, indent=1))
    print(c("eccx ready", "b"))
    print(f"  ECC source      {ECC_ROOT}  (v{read_text(ECC_ROOT / 'VERSION').strip()})")
    print("  components      " + ", ".join(f"{k}={v}" for k, v in st.items()
                                             if k != "tokens_if_all_loaded"))
    print(f"  index           {st['tokens_if_all_loaded']:,} tokens catalogued "
          f"(never loaded at once)")
    print(f"  project         {project}")
    print(f"  rule packs      {', '.join(_context_for(project))}")
    print(f"  memory          {msg}")
    return 0


def cmd_index(args) -> int:
    """Build (or rebuild) the index and say what is in it.

    Existed everywhere in the documentation and nowhere in the code: the index
    was built implicitly by whichever command ran first, so `eccx index` — the
    first line of every quickstart, including the one in CI — exited with
    `invalid choice: 'index'`. Found by cloning the repository cold and
    following its own README.
    """
    from . import semantic
    root = _corpus_root(args)
    if root is not None:
        from . import corpus
        idx = corpus.build(root)
        corpus.save(idx, _state_dir(root))
        st = corpus.stats(idx)
        n_sec = st["sections"]
        print(f"indexed {st['docs']} documents, {n_sec} sections, {st['tokens']:,} tokens")
        print("  kinds   " + ", ".join(f"{k} ({v})" for k, v in st["kinds"].items()))
        stored = _state_dir(root) / "index.json"
    else:
        idx = indexer.load(force=getattr(args, "force", False))
        n_sec = sum(len(d.get("sections") or []) for d in idx["docs"])
        counts: dict[str, int] = {}
        for d in idx["docs"]:
            counts[d["kind"]] = counts.get(d["kind"], 0) + 1
        # Report the root the *index* was built from, not the one configured
        # now. Without --force this command serves the cache, and printing
        # ECC_ROOT next to cached counts claims a rebuild that did not happen
        # — it cost ten minutes of chasing a 611-document catalogue that was
        # really a 607-document one plus a stale file.
        built_from = idx.get("ecc_root") or str(ECC_ROOT)
        cached = built_from != str(ECC_ROOT)
        print(f"indexed {len(idx['docs'])} components, {n_sec} sections "
              f"from {built_from}"
              + (f"  (cache ; ECC_ROOT vaut maintenant {ECC_ROOT})" if cached else ""))
        print("  kinds   " + ", ".join(f"{k} ({v})" for k, v in
                                       sorted(counts.items(), key=lambda kv: -kv[1])))
        stored = ADAPTER_STATE / "index.json"
    print(f"  stored  {stored}")
    # Reading the vectors needs numpy only; building them, and embedding a
    # query at run time, need fastembed. Reporting "not installed" as if the
    # vectors were missing would be wrong on a machine where they are built.
    allv = semantic.load_all(idx["docs"])
    if allv is None:
        print("  vectors not built")
        print("          pip install 'eccx[semantic]'   then: eccx vectors")
    else:
        extra = "" if allv.get("sections") is not None else " (documents only)"
        print(f"  vectors {allv['docs'].shape[0]} x {allv['docs'].shape[1]}{extra}")
        if not semantic.available():
            print("  fastembed absent — queries will route lexically until "
                  "`pip install 'eccx[semantic]'`")
    return 0


def cmd_vectors(args) -> int:
    """One-off cost: ~42 s for 607 components on 2 vCPU, then 8 ms per query."""
    from . import semantic
    if not semantic.available():
        print("fastembed is not installed.\n"
              "  pip install fastembed      # ~30 MB, no torch\n"
              "then re-run: eccx vectors", file=sys.stderr)
        return 2
    idx = _index(args)
    if not args.force:
        D = semantic.load_vectors(idx["docs"])
        if D is not None:
            print(f"vectors already current ({D.shape[0]} x {D.shape[1]}) "
                  f"— use --force to rebuild")
            return 0
    n = semantic.build_vectors(idx["docs"])
    print(f"embedded {n} components + their sections with {semantic.MODEL}")
    print(f"  stored  {semantic.VECTORS}")
    print("  use     eccx recall \"…\" --semantic")
    return 0


def cmd_doctor(args) -> int:
    checks = []
    ok = lambda n, d="": checks.append(("OK", n, d))
    warn = lambda n, d="": checks.append(("WARN", n, d))
    bad = lambda n, d="": checks.append(("FAIL", n, d))

    if ECC_ROOT.is_dir():
        ok("ECC source", str(ECC_ROOT))
    else:
        bad("ECC source", f"{ECC_ROOT} missing — clone affaan-m/ECC there")

    node = __import__("shutil").which("node")
    ok("node runtime", node) if node else warn("node runtime", "absent: memory vault disabled")

    if (ECC_ROOT / "node_modules").is_dir():
        ok("node deps", "installed")
    else:
        warn("node deps", f"run: cd {ECC_ROOT} && npm install --ignore-scripts (ou ./tools/vendor_bootstrap.sh)")

    idx = indexer.load_json_soft()
    if idx and idx.get("count"):
        ok("index", f"{idx['count']} components")
    else:
        warn("index", "not built yet — run: eccx init")

    mcp = []
    try:
        from . import mcp_client
        for name, srv in mcp_client.configured_servers().items():
            mcp.append(f"{name}{'' if mcp_client.bootable(srv.get('command','')) else '(unavailable)'}")
    except Exception:
        pass
    ok("mcp servers", ", ".join(mcp[:6]) or "none")

    if ADAPTER_STATE.exists():
        ok("adapter state", str(ADAPTER_STATE))
    else:
        warn("adapter state", "run: eccx init")

    print(c("eccx doctor", "b"))
    for status, name, detail in checks:
        color = {"OK": "g", "WARN": "y", "FAIL": "r"}[status]
        print(f"  [{c(status, color)}] {name:<16} {detail}")
    fails = sum(1 for s, _, _ in checks if s == "FAIL")
    print(f"\n  {len(checks)} checks, {fails} failure(s)")
    return 1 if fails else 0


def cmd_stats(args) -> int:
    idx = _index(args)
    st = indexer.stats(idx)
    print(c("ECC catalogue", "b"))
    for k in ("skill", "agent", "command", "rule", "guide", "manual"):
        if k in st:
            print(f"  {k:<9} {st[k]:>4}")
    print(f"  {'total':<9} {idx['count']:>4}")
    print(f"\n  if a harness loaded everything: {st['tokens_if_all_loaded']:,} tokens")
    print(f"  eccx recall budget default:      3,500 tokens "
          f"({3500 / st['tokens_if_all_loaded'] * 100:.1f}% of that)")
    return 0



def _semantic(index, query: str):
    """(matrix, vector) for the hybrid path, or (None, None).

    Degrades to the lexical router when `fastembed` is absent, when the model
    cannot be downloaded (offline), or when the vectors are stale. A routing
    tool that refuses to work because a 130 MB model is missing would be a
    worse product than one that routes 8 points worse.
    """
    from . import semantic
    if not semantic.available():
        print("# semantic: fastembed absent — lexical routing\n"
              "#   pip install fastembed   (once, then `eccx index --vectors`)",
              file=sys.stderr)
        return None, None
    allv = semantic.load_all(index["docs"])
    if allv is None:
        print("# semantic: vectors missing or stale — run `eccx vectors`",
              file=sys.stderr)
        return None, None
    try:
        return allv, semantic.embed_query(query)
    except Exception as e:                                   # network, disk, model
        print(f"# semantic unavailable ({type(e).__name__}) — lexical fallback",
              file=sys.stderr)
        return None, None


def _apply_profil(idx: dict, args) -> dict:
    """Filter the catalogue by a declared profile, at query time.

    Deliberately not at index time: the index stays complete and the profile is
    a view. Deleting 90 skills to gain 2 points at rank 1 was rejected (see
    docs/AUDIT-BASE.md) — a view can be dropped, a deletion cannot.
    """
    name = getattr(args, "profil", None)
    if not name:
        return idx
    from . import profil
    try:
        prof = profil.load(name)
    except profil.ProfileError as exc:
        die(str(exc))
    out = profil.apply(idx, prof)
    print(f"# profil {prof['id']} — {len(idx['docs'])} → {len(out['docs'])} documents",
          file=sys.stderr)
    return out


def cmd_recall(args) -> int:
    idx = _apply_profil(_index(args), args)
    project = _project(args)
    ctx = _context_for(project)
    kinds = args.kind.split(",") if getattr(args, "kind", None) else None
    tw = None
    if getattr(args, "expand", False):
        from . import expand as ex
        tw = ex.build_terms(idx, args.query)["weights"]
    pool = max(args.k, 15) if getattr(args, "rerank", False) else args.k
    if getattr(args, "semantic", False):
        allv, qv = _semantic(idx, args.query)
        if allv is None:
            results = router.score(idx, args.query, kinds=kinds, top=pool,
                                   project_context=ctx, boost=router.load_boost(),
                                   term_weights=tw)
        else:
            results = router.score_hybrid(idx, args.query, top=pool,
                                          vector_matrix=allv["docs"],
                                          section_matrix=allv["sections"],
                                          section_span=allv["span"],
                                          query_vector=qv, kinds=kinds,
                                          project_context=ctx,
                                          boost=router.load_boost(),
                                          term_weights=tw)
    else:
        results = router.score(idx, args.query, kinds=kinds, top=pool,
                               project_context=ctx, boost=router.load_boost(),
                               term_weights=tw)
    if getattr(args, "rerank", False):
        from . import rerank as rr
        results, used = rr.reranked_results(args.query, results)
        if not used and args.k:
            req = rr.build_request(args.query, results)
            print(f"# rerank needed ({req['gate']['reason']}) — run:\n"
                  f"#   eccx rerank \"{args.query}\"\n"
                  f"# then re-run with --rerank (cost ~{req['tokens']} tokens)\n")
        results = results[:args.k]
    if not results:
        _, noun = _source(args)
        print(f"No {noun} matches '{args.query}'. Try `eccx stats` for what exists.")
        return 0

    # The contract: below `CONFIDENT_MARGIN` the router does not claim to have
    # ranked; it hands over candidates and says so. Presenting an 18 %-precise
    # top-1 as "the route" was the tool lying about its own certainty.
    cos = None
    if getattr(args, "semantic", False):
        # Recompute the cosine of the winner cheaply: `score_hybrid` already had
        # it but the result rows carry only scores.
        try:
            from . import semantic as _sem
            D2 = _sem.load_vectors(idx["docs"])
            if D2 is not None:
                qv2 = _sem.embed_query(args.query)
                key = f"{results[0]['doc']['kind']}:{results[0]['doc']['id']}"
                ids2 = [f"{d['kind']}:{d['id']}" for d in idx["docs"]]
                cos = float(D2[ids2.index(key)] @ qv2)
        except Exception:
            cos = None
    verdict = router.confidence(results, cosine=cos)
    if verdict == "unsure":
        # `-k` is the caller's decision, not advice. Returning 3 candidates when
        # 2 were asked for is the same fault as exceeding `--budget`: the tool
        # deciding what the agent ingests. The verdict is reported; the count is
        # honoured.
        # stderr, not stdout, for two measured reasons:
        #   * `--json` must stay parseable (`jq` reads stdout only);
        #   * `--budget` is a hard cap on stdout, and this notice was spending
        #     20 of the caller's tokens — caught by tools/budget_smoke.py at
        #     420 tokens for `--budget 400`. The promise is about what the agent
        #     ingests, and the agent ingests stdout.
        print(f"# unsure (margin {router.margin_of(results):.2f} < "
              f"{router.CONFIDENT_MARGIN:.2f}) — {len(results)} candidate(s), "
              f"the router will not pick one for you"
              + ("; --k 3 gives it a fair chance" if args.k < 3 else ""),
              file=sys.stderr)

    if args.json:
        print(json.dumps({"verdict": verdict,
                          "confidence": round(cos, 3) if cos is not None
                          else round(router.margin_of(results), 3),
                          "candidates": [{"id": r["doc"]["id"], "kind": r["doc"]["kind"],
                                          "score": r["score"], "path": r["doc"]["path"],
                                          "coverage": r["coverage"]} for r in results]},
                         indent=1))
        return 0

    missing = _unreadable_routes(results)
    if missing:
        anchor = missing[0].parent.parent
        print(f"# content unavailable for {len(missing)}/{len(results)} route(s) — "
              f"{anchor} is missing or unreadable.\n"
              f"#   the route list above is metadata only; bodies live on disk. "
              f"Clone the catalogue or set ECC_ROOT, then re-run.", file=sys.stderr)
    label, noun = _source(args)
    scope = (f"routed to {len(results)} {noun}(s)"
             if label != "ECC"
             else f"routed to {len(results)} component(s); project packs: {', '.join(ctx)}")
    header = [
        f"# {label} context — \"{args.query}\"",
        f"_{scope}_",
        "",
        "## Route",
    ]
    for i, r in enumerate(results, 1):
        d = r["doc"]
        hint = ""
        if d["kind"] == "command" and d["extra"].get("argument_hint"):
            hint = f"  (args: {d['extra']['argument_hint']})"
        header.append(f"{i}. `{d['kind']}:{d['id']}` — {d['desc'][:110]}{hint}")
    header.append("")
    header.append("## Content")
    header.append("")
    # `--budget` covers the WHOLE output, banner and route map included. It
    # used to cover only the content, so `--k 8 --budget 400` emitted 670
    # tokens: the flag said "max tokens of content" and the caller counted
    # everything. The content now gets whatever the header leaves.
    head = "\n".join(header) + "\n"
    bundle = router.render_bundle(results,
                                  budget_tokens=max(0, args.budget - est_tokens(head)),
                                  query=args.query)
    out = head + bundle
    if args.max_tokens:
        out = truncate(out, args.max_tokens * 4)
    print(out)
    spent = _account(est_tokens(out), "recall")
    if args.stats:
        print(f"\n[{est_tokens(out)} tokens returned · {spent:,} today]",
              file=sys.stderr)
    if spent > 40000:
        print(f"[eccx] {spent:,} tokens injected today — prefer --k 2 / smaller "
              "--budget for narrow tasks.", file=sys.stderr)
    return 0


def cmd_show(args) -> int:
    idx = _index(args)
    doc = _find(idx, args.spec)
    if not doc:
        return 1
    path = doc_file(doc)
    body = read_text(path)
    _, content = fm.split(body) if doc["kind"] in ("skill", "agent", "command") else (None, body)
    out = content if content.strip() else body
    if args.max_tokens:
        out = truncate(out, args.max_tokens * 4)
    if args.json:
        print(json.dumps({**doc, "content": out}, indent=1))
    else:
        print(f"<!-- eccx show {doc['kind']}:{doc['id']} | {doc['path']} -->")
        print(out)
        print(f"\n<!-- {doc['body_tokens']} tokens full; returned {est_tokens(out)} -->",
              file=sys.stderr)
    return 0


def cmd_search(args) -> int:
    idx = _index(args)
    kinds = args.kind.split(",") if args.kind else None
    tw = None
    if getattr(args, "expand", False):
        from . import expand as ex
        tw = ex.build_terms(idx, args.query)["weights"]
    results = router.score(idx, args.query, kinds=kinds, top=args.k,
                           boost=router.load_boost(), term_weights=tw)
    if not results:
        print("no match")
        return 0
    for r in results:
        d = r["doc"]
        print(f"{c(d['kind'], 'c'):<16} {d['id']:<38} {r['score']:>6.2f}  {d['desc'][:80]}")
    return 0


def cmd_cmd(args) -> int:
    idx = _index(args)
    name = args.name
    doc = None
    for d in idx["docs"]:
        if d["kind"] == "command" and d["id"].lower() == name.lower():
            doc = d
            break
    if not doc:
        doc = _find(idx, f"command:{name}")
    if not doc:
        return 1
    text = read_text(doc_file(doc))
    meta, body = fm.split(text)
    arguments = " ".join(args.arguments)
    rendered = body.replace("$ARGUMENTS", arguments)
    for i, m in enumerate(arguments.split(), 1):
        rendered = rendered.replace(f"${i}", m)
    if args.task:
        preface = f"**Input**: {args.task}\n\n"
        if "$ARGUMENTS" not in body and not arguments:
            rendered = preface + rendered
    out = rendered
    if args.max_tokens:
        out = truncate(out, args.max_tokens * 4)
    if args.json:
        print(json.dumps({"command": doc["id"], "instructions": out}, indent=1))
        return 0
    print(f"<!-- eccx cmd {doc['id']} | {doc['path']} | args: {arguments or '(none)'} -->")
    print(f"# /{doc['id']}\n")
    print(out)
    return 0


def cmd_agent(args) -> int:
    idx = _index(args)
    doc = _find(idx, f"agent:{args.name}")
    if not doc:
        return 1
    text = read_text(doc_file(doc))
    meta, body = fm.split(text)
    parts = [f"<!-- eccx agent {doc['id']} | tools={meta.get('tools') or 'n/a'} -->",
             f"# Delegation brief: {doc['id']}", "", body.strip()]
    if args.task:
        parts += ["", "---", "", "## Task", args.task]
        routed = router.score(idx, args.task, kinds=["skill", "rule"], top=args.skills,
                              project_context=_context_for(_project(args)))
        if routed:
            parts += ["", "## Routed skills", ""]
            for r in routed:
                d = r["doc"]
                parts.append(f"### {d['kind']}:{d['id']}")
                parts.append(truncate(read_text(doc_file(d)), 1800))
                parts.append("")
    out = "\n".join(parts)
    if args.max_tokens:
        out = truncate(out, args.max_tokens * 4)
    print(out)
    return 0


def cmd_rules(args) -> int:
    idx = _index(args)
    project = _project(args)
    packs = args.packs.split(",") if args.packs else _context_for(project)
    if not packs:
        print("no rule pack matched; pass --packs typescript,python")
        return 0
    if args.list:
        for d in idx["docs"]:
            if d["kind"] == "rule" and d["extra"].get("pack") in packs:
                print(f"{d['extra']['pack']:<14} {d['id']}")
        return 0
    digest = router.suggest_rules(idx, packs, budget_tokens=args.budget)
    print(f"# ECC rules — packs: {', '.join(packs)}\n")
    print(digest or "(no rule files in these packs)")
    return 0


def cmd_fire(args) -> int:
    if args.payload:
        payload = json.loads(args.payload)
    elif not sys.stdin.isatty():
        raw = sys.stdin.read().strip()
        payload = json.loads(raw) if raw else {}
    else:
        payload = {}
    if args.tool:
        payload.setdefault("tool_name", args.tool)
    if args.file:
        payload.setdefault("tool_input", {})["file_path"] = args.file
    payload.setdefault("cwd", str(_project(args)))
    payload["hook_event_name"] = args.event
    code, messages = hooks.run(args.event, payload)
    for m in messages:
        is_blocking = code == 2 and any(m.startswith(x) for x in
                                        ("ECC config-protection", "ECC gateguard",
                                         "ECC mcp-health-check"))
        print(m, file=sys.stderr if is_blocking else sys.stdout)
    if args.json:
        print(json.dumps({"event": args.event, "exit": code, "messages": messages},
                         indent=1))
    return code


def cmd_tools(args) -> int:
    from . import mcp_client
    servers = mcp_client.configured_servers()
    if not servers:
        print("no mcp-configs/mcp-servers.json found")
        return 1
    if args.probe:
        recs = mcp_client.probe_all(servers, parallel=True,
                                    refresh=getattr(args, "refresh", False),
                                    ttl=args.ttl)
        ready = [r for r in recs if r["ok"]]
        print(f"{len(ready)}/{len(recs)} MCP servers bootable here"
              f"{' (cached)' if any(r.get('cached') for r in recs) else ''}\n")
        for rec in recs:
            status = c("ready", "g") if rec["ok"] else c(rec["status"], "y")
            suffix = " [cache]" if rec.get("cached") else ""
            print(f"{rec['name']:<18} {status:<12} {rec.get('detail', '')[:70]}{suffix}")
            if rec.get("tools"):
                print(f"{'':19}tools: {', '.join(rec['tools'][:8])}")
        return 0
    # Coverage found this loop behind `if False:` — `eccx tools` without --probe
    # printed a header and nothing else. Dead code is what a coverage number is
    # actually good at finding.
    for name, srv in servers.items():
        avail = mcp_client.bootable(srv.get("command", ""))
        tag = c("configured", "g") if avail else c("unavailable", "y")
        print(f"{name:<16} {tag:<18} {(srv.get('description') or '')[:90]}")
    return 0


def cmd_mcp(args) -> int:
    from . import mcp_client
    servers = mcp_client.configured_servers()
    if args.server not in servers:
        print(f"unknown server '{args.server}'. configured: {', '.join(servers)}")
        return 1
    srv = servers[args.server]
    if not args.tool:
        rec = mcp_client.probe(args.server, srv)
        print(json.dumps(rec, indent=1))
        return 0 if rec["ok"] else 1
    arguments = json.loads(args.args) if args.args else {}
    with mcp_client.StdioClient(srv.get("command", ""), srv.get("args", []),
                                srv.get("env"), timeout=args.timeout) as client:
        client.initialize()
        result = client.call_tool(args.tool, arguments)
    print(json.dumps(result, indent=1, ensure_ascii=False))
    return 0


def cmd_session(args) -> int:
    project = _project(args)
    if args.action == "init":
        print(memory.init(project))
    elif args.action == "save":
        body = args.body or (sys.stdin.read() if not sys.stdin.isatty() else "")
        if not body:
            print("nothing to save: pass --body or pipe text", file=sys.stderr)
            return 1
        res = memory.save(args.title or body[:60], body, kind=args.kind,
                          tags=args.tag or [], cwd=project)
        print(json.dumps(res, indent=1))
    elif args.action in ("search", "recall"):
        hits = memory.search(args.query or "", cwd=project, limit=args.limit,
                             scope=args.scope)
        if args.json:
            print(json.dumps(hits, indent=1))
            return 0
        if not hits:
            print("(memory empty or no match)")
            return 0
        for h in hits:
            print(f"[{h['trust'] or 'local'}] {h['id']} — {h['title']} ({h['kind']})")
            if h["body"]:
                print("   " + h["body"][:300].replace("\n", " "))
    elif args.action == "read":
        rec = memory.read(args.query or "", cwd=project)
        print(json.dumps(rec, indent=1) if rec else "not found")
    elif args.action == "start":
        code, msgs = hooks.run("SessionStart", {"cwd": str(project),
                                                "hook_event_name": "SessionStart"})
        print("\n".join(msgs) or "(nothing to bootstrap)")
    return 0


BRIEF = """# ECC operating brief (eccx)

This project is wired to **ECC** (github.com/affaan-m/ECC) through `eccx`, an
adapter that reproduces the four things Claude Code normally does for ECC:
skill discovery, routing, hooks, and MCP.

## Use it before starting work

```bash
eccx recall "<what you are about to do>"     # routes to the right ECC skill/agent
eccx show skill:<id>                          # read one component in full
eccx cmd <command> [args]                     # run a slash-command, $ARGUMENTS filled
eccx agent <agent> --task "<task>"            # delegated brief + routed skills
eccx rules                                    # rule pack matching this repo
eccx session save --title "..." --body "..."  # durable decision record
```

## Token discipline

ECC is {count} components / ~{tokens} tokens. Never load it wholesale — `eccx
recall` returns ~3.5k tokens of the *relevant* slice. That is the whole point of
the adapter.

## Rules of engagement

- Read the routed skill before writing code, not after.
- Persist decisions with `eccx session save`; they are recalled at session start.
- Hooks: config-protection, gateguard, console-log guard and governance capture
  are enforced through `eccx fire <Event>` with Claude Code's exit-code contract
  (exit 2 = blocked, message on stderr).
"""


def cmd_bootstrap(args) -> int:
    idx = _index(args)
    st = indexer.stats(idx)
    project = _project(args)
    text = BRIEF.format(count=idx["count"], tokens=f"{st['tokens_if_all_loaded']:,}")
    out = project / (args.out or "ECC-AGENT-BRIEF.md")
    out.write_text(text, encoding="utf-8")
    agents = project / "AGENTS.md"
    if args.patch_agents:
        if agents.exists():
            body = read_text(agents)
            if "eccx recall" not in body:
                agents.write_text(body.rstrip() + "\n\n## ECC\n\n"
                                  f"See {out.name}: use `eccx recall` before starting work.\n",
                                  encoding="utf-8")
                print(f"appended ECC pointer to {agents}")
        else:
            agents.write_text(f"# AGENTS\n\n## ECC\n\nSee {out.name}: use `eccx recall`.\n",
                              encoding="utf-8")
            print(f"created {agents}")
    print(f"wrote {out}")
    return 0


def cmd_learn(args) -> int:
    """Mine the observation log for repeated work worth turning into a skill."""
    path = ADAPTER_STATE / "observations.jsonl"
    if not path.exists():
        print("no observations yet — run `eccx fire` on tool events first")
        return 0
    counts: dict[str, int] = {}
    for line in path.read_text().splitlines():
        try:
            rec = json.loads(line)
        except Exception:
            continue
        if not isinstance(rec, dict):   # a log file is not a promise about types
            continue
        tool = rec.get("tool", "?")
        ext = Path(rec.get("target", "")).suffix or "cmd"
        counts[f"{tool}:{ext}"] = counts.get(f"{tool}:{ext}", 0) + 1
    print(c("observed patterns (candidates for a new skill)", "b"))
    for k, v in sorted(counts.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {v:>4}x  {k}")
    print(f"\n  total {sum(counts.values())} observation(s) in {path}")
    return 0


def cmd_rerank(args) -> int:
    """Emit a compact shortlist for the model, or apply the model's ordering."""
    from . import rerank as rr

    if args.apply_file:
        payload = json.loads(Path(args.apply_file).read_text(encoding="utf-8"))
        idx = _index(args)
        applied, failed = [], []
        for query, order in payload.items():
            results = rr.shortlist(idx, query, k=args.k,
                                   ctx=_context_for(_project(args)),
                                   boost=router.load_boost())
            try:
                applied.append({"q": query, **rr.apply_order(query, results, order)})
            except ValueError as exc:
                failed.append({"q": query, "error": str(exc)})
        print(json.dumps({"applied": len(applied), "failed": failed}, indent=1))
        for a in applied:
            flag = " (top changed)" if a["changed_top"] else ""
            print(f"  ok  {a['q'][:60]}{flag}")
        return 0 if not failed else 1

    idx = _index(args)
    ctx = _context_for(_project(args))

    if args.file:
        golden = [json.loads(l) for l in
                  Path(args.file).read_text(encoding="utf-8").splitlines() if l.strip()]
        queries = [g["q"] for g in golden]
        n, m = max(1, args.batch), max(1, args.of)
        size = -(-len(queries) // m)          # ceil division
        chunk = queries[(n - 1) * size: n * size]
        print(f"<!-- rerank batch {n}/{m}: {len(chunk)} queries. "
              f"Answer with JSON {{query: [ordered ids]}}. -->")
        total = 0
        for q in chunk:
            res = rr.shortlist(idx, q, k=args.k, ctx=ctx, boost=router.load_boost())
            req = rr.build_request(q, res)
            total += req["tokens"]
            print(f"\n### {q}")
            print(req["cards"])
        print(f"\n<!-- shortlist cost: {total} tokens, "
              f"{total / max(1, len(chunk)):.0f}/query -->")
        return 0

    if not args.query:
        print("usage: eccx rerank \"<query>\" | --apply-file f.json | "
              "--file evals/heldout.jsonl --batch 1 --of 3")
        return 1
    res = rr.shortlist(idx, args.query, k=args.k, ctx=ctx,
                       boost=router.load_boost())
    req = rr.build_request(args.query, res)
    cached = rr.lookup(args.query, req["candidates"])
    if args.json:
        print(json.dumps({**req, "cached": cached}, indent=1, ensure_ascii=False))
        return 0
    print(f"# rerank request — \"{args.query}\"")
    print(f"# gate: {'confident, rerank optional' if req['gate']['confident'] else 'NOT confident'}"
          f" ({req['gate']['reason']}, gap={req['gate']['gap']})")
    print(f"# cost: ~{req['tokens']} tokens for {len(req['candidates'])} candidates\n")
    print(req["cards"])
    if cached:
        print(f"\ncached order: {', '.join(cached['order'][:3])} …")
    else:
        print(f"\nanswer: eccx rerank --apply-file <json>  "
              f"key={req['key']}")
    return 0


def _quality_block(idx: dict) -> dict:
    """Report measured quality, never a hardcoded claim.

    dev = the set used to tune thresholds.  heldout = authored blind, used once.
    Reporting both is the whole point: dev alone flatters the router.
    """
    from . import evaluate
    out: dict = {}
    dev = evaluate.load_golden()
    r = evaluate.run(idx, dev)
    out["dev"] = {"intents": r["metrics"]["cases"],
                  **{k: r["metrics"][k] for k in ("recall@1", "recall@3", "recall@5", "mrr")}}
    # Two held-out sets, in the order they were written. Each was authored
    # before the feature it measures, and opened once.
    for name in ("heldout", "heldout2"):
        path = ADAPTER_ROOT / "evals" / f"{name}.jsonl"
        if not path.is_file():
            continue
        held = evaluate.load_golden(path)
        base = evaluate.run(idx, held)
        rer = evaluate.run(idx, held, rerank=True)
        block = {
            "intents": base["metrics"]["cases"],
            "baseline": {k: base["metrics"][k] for k in ("recall@1", "recall@3", "mrr")},
            "reranked": {k: rer["metrics"][k] for k in ("recall@1", "recall@3", "mrr")},
            "rerank_coverage": rer["metrics"].get("rerank_coverage"),
            "escalated_share": rer["metrics"].get("escalated"),
        }
        try:
            for k in (15, 30):
                ceil = sum(
                    1 for g in held
                    if set(f"{x['doc']['kind']}:{x['doc']['id']}"
                           for x in router.score(idx, g["q"], top=k))
                    & set(g["expect"]))
                block[f"retrieval_ceiling@{k}"] = round(ceil / len(held), 3)
        except Exception:
            pass
        out[name] = block
    # Expansion is measured and negative; surfaced so nobody enables it by hope.
    path = ADAPTER_ROOT / "evals" / "heldout2.jsonl"
    if path.is_file():
        held = evaluate.load_golden(path)
        exp_ = evaluate.run(idx, held, expand=True)
        out["rocchio_expansion"] = {
            "recall@1": exp_["metrics"]["recall@1"],
            "recall@3": exp_["metrics"]["recall@3"],
            "verdict": "negative — opt-in only",
        }
    return out


def cmd_manifest(args) -> int:
    idx = _index(args)
    data = {
        "adapter": "eccx",
        "version": "1.0.0",
        "ecc_root": str(ECC_ROOT),
        "ecc_version": read_text(ECC_ROOT / "VERSION").strip(),
        "counts": indexer.stats(idx),
        "hooks": {ev: ids for ev, ids in hooks.EVENT_MAP.items()},
        "inert_hooks": sorted(hooks.INERT),
        "capabilities": {
            "skill_discovery": True,
            "routing": True,
            "section_level_retrieval": True,
            "slash_commands": True,
            "subagents_as_briefs": True,
            "hooks_advisory": True,
            "hooks_enforced_by_git": True,
            "hook_contract": "claude-code (exit 2 = deny)",
            "mcp_client": True,
            "mcp_parallel_probe": True,
            "memory": True,
            "routing_eval": True,
            "feedback_loop": True,
            "token_accounting": True,
            "long_running_daemon": False,
            "parallel_subagent_execution": False,
        },
        "quality": _quality_block(idx),
    }
    print(json.dumps(data, indent=1))
    return 0



# ------------------------------------------------- enforcement / quality / ops

def _feedback_path():
    return ADAPTER_STATE / "feedback.json"


def _record_feedback(component: str, good: bool, weight: int = 1) -> dict:
    from .util import load_json, locked, save_json
    path = _feedback_path()
    # Read-modify-write: without the lock, two `eccx feedback` calls in flight
    # keep only the later one. Same defect class as the rerank cache.
    with locked(path):
        data = load_json(path, {}) or {}
        rec = data.setdefault(component, {"good": 0, "bad": 0})
        rec["good" if good else "bad"] += weight
        rec["last"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        save_json(path, data)
    return rec


def _account(tokens: int, command: str) -> int:
    """Cumulative token spend for the day, so recall cannot quietly blow up."""
    from .util import load_json, save_json
    path = ADAPTER_STATE / "session.json"
    today = time.strftime("%Y-%m-%d")
    from .util import locked
    with locked(path):
        data = load_json(path, {}) or {}
        if data.get("date") != today:
            data = {"date": today, "tokens": 0, "calls": []}
        data["tokens"] += tokens
        data["calls"].append({"cmd": command, "tokens": tokens,
                              "at": time.strftime("%H:%M:%S")})
        data["calls"] = data["calls"][-40:]
        save_json(path, data)
    return data["tokens"]


def cmd_install_hooks(args) -> int:
    from . import enforce
    project = _project(args)
    action = args.action
    if action == "uninstall":
        res = enforce.uninstall(project)
        print(json.dumps(res, indent=1))
        return 0 if res["ok"] else 1
    res = enforce.install(project, force=args.force)
    print(json.dumps(res, indent=1))
    if res["ok"]:
        print("\nPre-commit now enforces: config-protection, secret-scan, "
              "console-log warning.\nThese fire on every `git commit`, including "
              "commits made by an agent — no discipline required.")
    return 0 if res["ok"] else 1


def cmd_precommit(args) -> int:
    from . import enforce
    project = _project(args)
    code, messages = enforce.precommit(project)
    if code == 0:
        for m in messages:
            print(f"  {m}")
        print("eccx pre-commit: ok")
    return code


def cmd_eval(args) -> int:
    from . import evaluate
    idx = _index(args)
    golden = evaluate.load_golden(Path(args.file) if args.file else None)
    # `k=args.k` was missing: `--k 20` evaluated a top-5 pool and reported
    # recall@20 for it. Every depth above 5 was silently the same number.
    res = evaluate.run(idx, golden, k=args.k, sections=getattr(args, "sections", True),
                       project_context=_context_for(_project(args)),
                       rerank=args.rerank, shortlist_k=args.shortlist,
                       expand=getattr(args, "expand", False),
                       semantic=getattr(args, "semantic", False))
    if args.json:
        print(json.dumps(res["metrics"], indent=1))
    else:
        print(evaluate.report(res, verbose=not args.quiet))
    m = res["metrics"]
    return 0 if m[f"recall@{args.k}"] >= args.min_recall else 1


GAPS = Path(__file__).resolve().parent.parent / "evals" / "gaps.json"


def cmd_gaps(args) -> int:
    """Definition of done, per catalogue gap — executable, not prose.

    §20 of docs/QUALITY.md argues that "coverage percentage" cannot tell you
    whether a *hole* is filled. This is what can: for each hole, the query that
    motivated it, the component that must win it, and an honest `claimed` flag.

    A gap is DONE when the production pipeline (resolve: lexical -> projection
    -> cascade) puts the expected component first. A gap marked `claimed:
    false` is reported but does not fail the gate — that is the difference
    between "we shipped something" and "we claim it works".
    """
    from . import rerank as rr
    path = Path(args.file) if args.file else GAPS
    try:
        gaps = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"cannot read {path}: {exc}")
        return 1

    idx = _index(args)
    known = {f"{d['kind']}:{d['id']}" for d in idx["docs"]}
    rows, failed = [], []
    for gap in gaps:
        want = gap["expect"][0]
        res, meta = rr.resolve(idx, gap["query"], k=args.shortlist)
        got = f"{res[0]['doc']['kind']}:{res[0]['doc']['id']}" if res else None
        doc = next((d for d in idx["docs"] if f"{d['kind']}:{d['id']}" == want), None)

        contract = {
            "indexed": want in known,
            "file": bool(doc) and doc_file(doc).is_file(),
            "body": bool(doc) and doc["body_tokens"] > 20,
            "desc": bool(doc) and len(doc.get("desc") or "") >= 40,
        }
        ok = got == want and all(contract.values())
        claimed = bool(gap.get("claimed", True))
        if claimed and not ok:
            failed.append(gap["id"])
        rows.append({**gap, "got": got, "ok": ok, "claimed": claimed,
                     "contract": contract, "depth": meta.get("depth"),
                     "gap_id": gap["id"]})

    if args.json:
        print(json.dumps(rows, indent=1, ensure_ascii=False))
    else:
        print(c("eccx gaps", "b") + f"  ({len(rows)} trous déclarés)")
        for r in rows:
            mark = c("DONE", "g") if r["ok"] else c("MISS", "r")
            tag = "" if r["claimed"] else c("  [non revendiqué]", "y")
            print(f"  {mark}  {r['gap_id']:<22} attendu {r['expect'][0]:<32} "
                  f"obtenu {r['got'] or '(vide)':<32} k={r['depth']}{tag}")
            bad = [k for k, v in r["contract"].items() if not v]
            if bad:
                print(f"        {c('contrat incomplet', 'r')} : {', '.join(bad)}")
            if not r["ok"]:
                print(f"        {c(r['why'][:150], 'dim')}")
        claimed = [r for r in rows if r["claimed"]]
        print(f"\n  {sum(1 for r in claimed if r['ok'])}/{len(claimed)} trous "
              f"revendiqués sont tenus")
    return 1 if failed else 0


def cmd_expand(args) -> int:
    """Show, verbatim, what query expansion would add. No hidden magic."""
    from . import expand as ex
    idx = _index(args)
    e = ex.build_terms(idx, args.query, k_docs=args.k_docs, beta=args.beta,
                       max_terms=args.max_terms, consensus=not args.no_consensus,
                       name_only=not args.all_fields)
    print(f"# expansion — \"{args.query}\"")
    print(f"# seeds: {', '.join(e['seed']) or '(none)'}")
    print(f"# added: {', '.join(e['added']) or '(none — nothing discriminative found)'}")
    if args.weights:
        for t, w in sorted(e['weights'].items(), key=lambda kv: -kv[1])[:20]:
            tag = "orig" if w >= 1.0 else "exp "
            print(f"  {tag} {t:<22} {w:.3f}")
    print("\nNOTE: measured negative on this catalogue — opt-in via --expand only.")
    return 0


def cmd_feedback(args) -> int:
    idx = _index(args)
    doc = _find(idx, args.spec)
    if not doc:
        return 1
    key = f"{doc['kind']}:{doc['id']}"
    rec = _record_feedback(key, good=args.good, weight=args.weight)
    print(f"{key}: +{rec['good']} good / +{rec['bad']} bad")
    print("Router will re-rank near-ties accordingly.")
    return 0


def cmd_review(args) -> int:
    """Assemble ECC's review skill *with the actual diff* — the real use case."""
    import subprocess
    project = _project(args)
    idx = _index(args)
    if args.staged:
        cmd = ["git", "-C", str(project), "diff", "--cached"]
    elif args.range:
        cmd = ["git", "-C", str(project), "diff", args.range]
    else:
        cmd = ["git", "-C", str(project), "diff", "HEAD"]
    diff = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    if not diff.strip():
        print("no diff to review (try --staged or --range HEAD~1)")
        return 0
    files = sorted({ln[6:] for ln in diff.splitlines() if ln.startswith("+++ b/")})
    ctx = _context_for(project)
    query = "code review of a diff touching " + (", ".join(files[:6]) or "code")
    results = router.score(idx, query, kinds=["skill", "command", "rule"], top=3,
                           project_context=ctx, boost=router.load_boost())
    # For a review we want the *procedure*, not a section of it: command bodies
    # are short, and $ARGUMENTS must carry the file list so PR/local mode
    # selection resolves correctly.
    top = results[0]["doc"] if results else None
    if top and top["kind"] == "command":
        raw = read_text(doc_file(top))
        meta, cbody = fm.split(raw)
        rendered = cbody.replace("$ARGUMENTS", " ".join(files[:8]))
        for i, f in enumerate(files[:8], 1):
            rendered = rendered.replace(f"${i}", f)
        body = (f"<!-- command:{top['id']} | {top['path']} -->\n" + rendered)
        if len(body) > (args.budget // 2) * 4:
            body = truncate(body, (args.budget // 2) * 4)
    else:
        body = router.render_bundle(results, budget_tokens=args.budget // 2, query=query)
    diff_part = truncate(diff, (args.budget // 2) * 3)
    print(f"# ECC review — {len(files)} file(s), packs: {', '.join(ctx)}\n")
    print("## Diff under review\n```diff")
    print(diff_part)
    print("```\n")
    print("## ECC review procedure")
    print(body)
    _account(est_tokens(diff_part + body), "review")
    return 0


def cmd_validate(args) -> int:
    """Enforce upstream's component contract on the local overlay."""
    from . import validate as vd
    res = vd.run(cross_check=not args.no_cross_check)
    print(c("eccx validate", "b"))
    print(f"  overlay   {res['skills']} skill(s) in skills-local/")
    for e in res["errors"]:
        print(f"  {c('ERROR', 'r')} {e}")
    for m in res["mismatches"]:
        print(f"  {c('MISMATCH', 'y')} {m}  (parser disagrees with js-yaml)")
    if res["ok"]:
        print(f"  {c('OK', 'g')} frontmatter conforme · parser cross-checked")
    return 0 if res["ok"] else 1


def cmd_audit(args) -> int:
    """Validate the index against the source: the adapter must not misread ECC."""
    import random
    from . import frontmatter as fm
    idx = _index(args)
    # Two severities, and the distinction is the point: `problems` are OUR
    # defects (the adapter misread, or points at nothing) and fail the gate;
    # `warnings` are upstream data quality (ECC ships two skills with an empty
    # description). Mixing them means either the gate is always red, or real
    # defects hide behind tolerated noise.
    problems: list[str] = []
    warnings: list[str] = []
    empty_desc = [d for d in idx["docs"] if not d.get("desc")]
    no_sections = [d for d in idx["docs"] if not d.get("sections")]
    if empty_desc:
        warnings.append(f"{len(empty_desc)} doc(s) without description (upstream): "
                        + ", ".join(d["id"] for d in empty_desc[:5]))
    if no_sections:
        warnings.append(f"{len(no_sections)} doc(s) without sections (upstream): "
                        + ", ".join(d["id"] for d in no_sections[:5]))

    for d in idx["docs"]:
        local = d.get("extra", {}).get("origin") == "local"
        if d["kind"] == "skill" and d["id"] != d["name"]:
            msg = f"skill '{d['id']}' frontmatter name is '{d['name']}'"
            (problems if local else warnings).append(msg)
        if not doc_file(d).is_file():
            problems.append(f"index points at a missing file: {d['path']}")

    # Cross-validate the hand-written frontmatter parser against a real YAML
    # parser (js-yaml ships with the ECC clone).
    sample = random.sample(idx["docs"], min(args.sample, len(idx["docs"])))
    mismatches = []
    node = __import__("shutil").which("node")
    if node:
        # Self-heal before giving up: node_modules is snapshot-excluded, so on a
        # fresh session the cross-check would silently degrade to "skipped" and
        # the gate would stay green without checking anything.
        from .util import ensure_ecc_deps
        ensure_ecc_deps(quiet=True)
    have_yaml = bool(node) and (ECC_ROOT / "node_modules" / "js-yaml").is_dir()
    if have_yaml:
        payload = []
        for d in sample:
            meta, _ = fm.split(read_text(doc_file(d)))
            payload.append({"path": str(doc_file(d)), "mine": meta})
        script = (
            "const yaml=require(process.argv[1]+'/node_modules/js-yaml');"
            "const fs=require('fs');"
            "const inp=JSON.parse(fs.readFileSync(0,'utf8'));"
            "const out=[];"
            "for(const it of inp){const t=fs.readFileSync(it.path,'utf8');"
            "const m=t.match(/^---\\n([\\s\\S]*?)\\n---/);"
            "let ref={};"
            "if(m){try{ref=yaml.load(m[1])||{}}catch(e){ref={__parse_error:String(e)}}}"
            "out.push({path:it.path,mine:it.mine,ref});}"
            "process.stdout.write(JSON.stringify(out));"
        )
        try:
            proc = __import__("subprocess").run(
                [node, "-e", script, str(ECC_ROOT)], input=json.dumps(payload),
                capture_output=True, text=True, timeout=120)
            if proc.returncode != 0:
                problems.append(f"cross-validation failed: {proc.stderr.strip()[:200]}")
            for row in json.loads(proc.stdout or "[]"):
                ref = row.get("ref") or {}
                for key in ("name", "description", "argument-hint", "tools", "model"):
                    mine_v = (row["mine"].get(key) or "").strip()
                    ref_v = ref.get(key)
                    ref_v = "" if ref_v is None else str(ref_v).strip()
                    if key in ref and mine_v.split()[:6] != ref_v.split()[:6]:
                        mismatches.append(f"{row['path']}: '{key}' mine={mine_v[:60]!r} "
                                          f"ref={ref_v[:60]!r}")
        except Exception as exc:
            problems.append(f"cross-validation skipped: {exc}")
    else:
        problems.append("cross-validation unavailable: node or js-yaml missing")

    print(c("eccx audit", "b"))
    print(f"  docs {idx['count']} · sections {idx.get('count_sections')} · "
          f"cross-checked {len(sample)} files")
    if mismatches:
        print(f"  {len(mismatches)} frontmatter mismatch(es) vs js-yaml:")
        for m in mismatches[:10]:
            print(f"    {m}")
    elif node:
        print("  frontmatter parser agrees with js-yaml on the sample")
    for w in warnings:
        print(f"  {c('WARN', 'y')} {w}")
    for pr in problems:
        print(f"  {c('PROBLEM', 'r')} {pr}")
    if not problems and not mismatches:
        print(f"  {c('OK', 'g')} index consistent with source")
    # `problems` used to be printed and then ignored: the gate exited 0 while
    # reporting "index points at a missing file". A check that cannot fail is
    # not a check — it is a log line.
    return 0 if (not problems and not mismatches) else 1


def cmd_sync(args) -> int:
    import subprocess
    before = read_text(ECC_ROOT / "VERSION").strip()
    print(f"ECC {before} → pulling…")
    proc = subprocess.run(["git", "-C", str(ECC_ROOT), "pull", "--ff-only"],
                          capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        print(f"pull failed: {proc.stderr.strip()[:300]}")
        return 1
    print(proc.stdout.strip()[:400] or "(already up to date)")
    after = read_text(ECC_ROOT / "VERSION").strip()
    idx = indexer.build()
    st = indexer.stats(idx)
    print(f"ECC {before} → {after} · reindexed {st['skill']} skills, "
          f"{st.get('sections', 0)} sections")
    if before != after:
        print(f"{c('version changed', 'y')} — rerun `eccx eval` to confirm routing "
              "did not regress.")
    return 0


def cmd_report(args) -> int:
    from .util import load_json
    data = load_json(ADAPTER_STATE / "session.json", {}) or {}
    if not data:
        print("no session data yet")
        return 0
    print(c(f"ECC usage — {data.get('date')}", "b"))
    print(f"  tokens injected   {data.get('tokens', 0):,}")
    idx = _index(args)
    catalogue = indexer.stats(idx)["tokens_if_all_loaded"]
    if data.get("tokens"):
        print(f"  catalogue         {catalogue:,}")
        print(f"  ratio             {data['tokens'] / catalogue * 100:.2f}% "
              f"(x{catalogue / data['tokens']:.0f} cheaper than loading ECC)")
    print("  last calls:")
    for c_ in data.get("calls", [])[-8:]:
        print(f"    {c_.get('at', '')}  {c_.get('cmd', ''):<14} {c_.get('tokens', 0):>6} tokens")
    return 0


# ------------------------------------------------------------------- argparse

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="eccx",
        description="ECC adapted for a harness-less agent sandbox.")
    p.add_argument("--project", default=None,
                   help="project root used for rule-pack detection and memory (default: cwd)")
    p.add_argument("-V", "--version", action="version",
                   version=f"eccx {_package_version()}",
                   help="print the version and exit")
    p.add_argument("--profil", default=None, metavar="NOM",
                   help="restreindre le catalogue à un profil déclaré (voir profils/) ; "
                        "réversible, aucun fichier supprimé — `eccx profils` pour la liste")
    p.add_argument("--corpus", default=None, metavar="DIR",
                   help="route over your own markdown instead of the ECC catalogue "
                        "(see `eccx corpus build --dir DIR`)")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("index", help="build the index and report what it contains")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_index)

    s = sub.add_parser("vectors", help="build local embedding vectors for --semantic")
    s.add_argument("--force", action="store_true", help="rebuild even if current")
    s.set_defaults(func=cmd_vectors)

    s = sub.add_parser("init", help="build the index, init memory, detect packs")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("doctor", help="check that every layer works")
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("stats", help="catalogue size and token budget maths")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("recall", help="route a task to ECC components within a budget")
    s.add_argument("query")
    s.add_argument("--k", type=int, default=4)
    s.add_argument("--budget", type=int, default=3500, help="max tokens of content")
    s.add_argument("--kind", default=None, help="skill,agent,command,rule")
    s.add_argument("--max-tokens", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.add_argument("--stats", action="store_true")
    s.add_argument("--rerank", action="store_true",
                   help="use the cached model rerank when available")
    s.add_argument("--expand", action="store_true",
                   help="Rocchio expansion (measured negative; opt-in)")
    s.add_argument("--semantic", dest="semantic", action="store_true", default=True,
                   help="fuse local embeddings into the ranking (default when "
                        "vectors exist)")
    s.add_argument("--no-semantic", dest="semantic", action="store_false",
                   help="pure lexical routing (~690 ms faster, ~5 points worse @1 "
                        "on held-out)")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("context", help="alias of recall with a smaller default budget")
    s.add_argument("query")
    s.add_argument("--k", type=int, default=3)
    s.add_argument("--budget", type=int, default=2000)
    s.add_argument("--kind", default=None)
    s.add_argument("--max-tokens", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.add_argument("--stats", action="store_true")
    s.set_defaults(func=cmd_recall)

    s = sub.add_parser("show", help="print one component")
    s.add_argument("spec")
    s.add_argument("--max-tokens", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("search", help="rank components without loading them")
    s.add_argument("query")
    s.add_argument("--k", type=int, default=8)
    s.add_argument("--kind", default=None)
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("cmd", help="render a slash-command with arguments")
    s.add_argument("name")
    s.add_argument("arguments", nargs="*")
    s.add_argument("--task", default=None)
    s.add_argument("--max-tokens", type=int, default=0)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_cmd)

    s = sub.add_parser("agent", help="build a delegation brief for an ECC agent")
    s.add_argument("name")
    s.add_argument("--task", default=None)
    s.add_argument("--skills", type=int, default=3)
    s.add_argument("--max-tokens", type=int, default=0)
    s.set_defaults(func=cmd_agent)

    s = sub.add_parser("rules", help="emit the rule digest for a project")
    s.add_argument("--packs", default=None)
    s.add_argument("--budget", type=int, default=1200)
    s.add_argument("--list", action="store_true")
    s.set_defaults(func=cmd_rules)

    s = sub.add_parser("fire", help="run the hook graph for an event")
    s.add_argument("event", choices=list(hooks.EVENT_MAP) + ["PostToolUseFailure"])
    s.add_argument("--tool", default=None)
    s.add_argument("--file", default=None)
    s.add_argument("--payload", default=None, help="JSON payload")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_fire)

    s = sub.add_parser("tools", help="list MCP servers")
    s.add_argument("--probe", action="store_true", help="really handshake each server")
    s.add_argument("--refresh", action="store_true", help="ignore the probe cache")
    s.add_argument("--ttl", type=int, default=3600, help="probe cache lifetime (s)")
    s.set_defaults(func=cmd_tools)

    s = sub.add_parser("mcp", help="call an MCP tool over stdio")
    s.add_argument("server")
    s.add_argument("tool", nargs="?", default=None)
    s.add_argument("--args", default=None, help="JSON arguments")
    s.add_argument("--timeout", type=float, default=20.0)
    s.set_defaults(func=cmd_mcp)

    s = sub.add_parser("session", help="durable memory")
    s.add_argument("action", choices=["init", "save", "search", "recall", "read", "start"])
    s.add_argument("query", nargs="?", default="")
    s.add_argument("--title", default=None)
    s.add_argument("--body", default=None)
    s.add_argument("--kind", default="note")
    s.add_argument("--tag", action="append")
    s.add_argument("--limit", type=int, default=8)
    s.add_argument("--scope", default="project")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_session)

    s = sub.add_parser("bootstrap", help="write an ECC brief into a project")
    s.add_argument("--out", default=None)
    s.add_argument("--patch-agents", action="store_true")
    s.set_defaults(func=cmd_bootstrap)

    s = sub.add_parser("learn", help="mine observations for repeated patterns")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("expand", help="show what Rocchio query expansion would add")
    s.add_argument("query")
    s.add_argument("--k-docs", type=int, default=3)
    s.add_argument("--beta", type=float, default=0.30)
    s.add_argument("--max-terms", type=int, default=8)
    s.add_argument("--no-consensus", action="store_true")
    s.add_argument("--all-fields", action="store_true")
    s.add_argument("--weights", action="store_true")
    s.set_defaults(func=cmd_expand)

    s = sub.add_parser("rerank", help="shortlist for the model, or apply its ordering")
    s.add_argument("query", nargs="?", default=None)
    s.add_argument("--k", type=int, default=15)
    s.add_argument("--json", action="store_true")
    s.add_argument("--apply-file", default=None, help="JSON {query: [ordered ids]}")
    s.add_argument("--file", default=None, help="golden file to emit batches from")
    s.add_argument("--batch", type=int, default=1)
    s.add_argument("--of", type=int, default=1)
    s.set_defaults(func=cmd_rerank)

    s = sub.add_parser("manifest", help="machine-readable capability report")
    s.set_defaults(func=cmd_manifest)

    s = sub.add_parser("gaps", help="definition of done per catalogue gap (executable)")
    s.add_argument("--file", default=None)
    s.add_argument("--shortlist", type=int, default=15)
    s.add_argument("--semantic", action="store_true",
                   help="fuse local embeddings into the ranking")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_gaps)

    s = sub.add_parser("eval", help="measure routing quality against the golden set")
    s.add_argument("--file", default=None)
    s.add_argument("--k", type=int, default=5)
    s.add_argument("--min-recall", type=float, default=0.9)
    s.add_argument("--rerank", action="store_true")
    s.add_argument("--expand", action="store_true",
                   help="Rocchio expansion (measured negative; opt-in)")
    s.add_argument("--shortlist", type=int, default=15)
    s.add_argument("--semantic", dest="semantic", action="store_true", default=True)
    s.add_argument("--no-semantic", dest="semantic", action="store_false",
                   help="measure the lexical router alone")
    s.add_argument("--no-sections", dest="sections", action="store_false",
                   help="score components at document level only (the A/B arm "
                        "that section retrieval was measured against)")
    s.add_argument("--quiet", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_eval)

    c = sub.add_parser("corpus", help="index an arbitrary directory of markdown")
    cs = c.add_subparsers(dest="action", required=True)
    cb = cs.add_parser("build", help="index DIR (markdown/text)")
    cb.add_argument("--dir", default=None,
                    help="dossier à indexer (défaut : --corpus, sinon .)")
    cb.set_defaults(func=cmd_corpus)
    ct = cs.add_parser("stats", help="what the index contains")
    ct.add_argument("--dir", default=None)
    ct.set_defaults(func=cmd_corpus)

    s = sub.add_parser("feedback", help="tell the router a component helped")
    s.add_argument("spec")
    s.add_argument("--good", dest="good", action="store_true", default=True)
    s.add_argument("--bad", dest="good", action="store_false")
    s.add_argument("--weight", type=int, default=1)
    s.set_defaults(func=cmd_feedback)

    s = sub.add_parser("install-hooks", help="install the enforced git pre-commit hook")
    s.add_argument("action", nargs="?", default="install",
                   choices=["install", "uninstall"])
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_install_hooks)

    s = sub.add_parser("precommit", help="run the blocking checks over staged files")
    s.set_defaults(func=cmd_precommit)

    s = sub.add_parser("review", help="ECC review procedure + the actual diff")
    s.add_argument("--staged", action="store_true")
    s.add_argument("--range", default=None)
    s.add_argument("--budget", type=int, default=3000)
    s.set_defaults(func=cmd_review)

    s = sub.add_parser("validate", help="check local overlay against ECC's skill contract")
    s.add_argument("--no-cross-check", action="store_true")
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("audit", help="validate the index against the ECC source")
    s.add_argument("--sample", type=int, default=40)
    s.set_defaults(func=cmd_audit)

    s = sub.add_parser("sync", help="pull upstream ECC and reindex")
    s.set_defaults(func=cmd_sync)

    s = sub.add_parser("report", help="token spend for the current session/day")
    s.set_defaults(func=cmd_report)
    return p


def cmd_corpus(args) -> int:
    from . import corpus
    if args.action == "build":
        # `--corpus DIR corpus build` and `corpus build --dir DIR` name the
        # same thing. They used to disagree: the global flag was ignored here,
        # so `eccx --corpus mes-notes corpus build` silently indexed the
        # current directory, and the `recall` that followed said "no corpus
        # index for mes-notes". Found by installing the wheel in a clean venv
        # and running the sequence a new user would run.
        root = Path(args.dir or getattr(args, "corpus", None) or ".").expanduser().resolve()
        idx = corpus.build(root)
        state = _state_dir(root)
        corpus.save(idx, state)
        st = corpus.stats(idx)
        print(f"indexed {st['docs']} documents, {st['sections']} sections, "
              f"{st['tokens']:,} tokens")
        print("  kinds   " + ", ".join(f"{k} ({v})" for k, v in st["kinds"].items()))
        print(f"  stored  {state / 'index.json'}")
        if st["no_sections"]:
            print(f"  WARNING {st['no_sections']} document(s) have no heading — "
                  f"they can only be found by document-level similarity")
        print(f"\n  next:  eccx --corpus {root} vectors")
        return 0
    if args.action == "stats":
        root = Path(args.dir or getattr(args, "corpus", None) or ".").expanduser().resolve()
        state = _state_dir(root)
        if not (state / "index.json").exists():
            die(f"no corpus index for {root}")
        idx = corpus.load_from(state)
        st = corpus.stats(idx)
        print(f"corpus   {idx['root']}")
        print(f"documents {st['docs']}   sections {st['sections']}   "
              f"tokens {st['tokens']:,}")
        print(f"sections/doc {st['sections_per_doc']}   "
              f"median doc {st['median_tokens_per_doc']} tokens   "
              f"without sections {st['no_sections']}")
        for k, v in st["kinds"].items():
            print(f"  {k:20s} {v}")
        if corpus.is_stale(idx):
            print("\n# files changed since the build — rerun `eccx corpus build`")
        return 0
    die(f"unknown corpus action: {args.action}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # One active corpus per process. Set here, once, so no command has to
    # remember to ask; `--corpus` on a single invocation is then enough for
    # recall, eval, vectors and context alike.
    _use_corpus_state(_corpus_root(args))
    try:
        return args.func(args)
    except indexer.CatalogueAbsent as exc:
        # A missing catalogue is an environment problem with one known fix,
        # not a traceback. Exit 2 so a script can tell it apart from a no-hit.
        print(c("catalogue absent", "r") + f"  {exc}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130
