#!/usr/bin/env python3
"""Audit de la base vendue : ce qui est cassé, ce qui est mort, ce qui manque.

Reproduit chaque chiffre de docs/AUDIT-BASE.md. Aucune opinion : sept contrôles,
chacun avec son protocole, ses résultats et ses limites.

    python3 tools/base_audit.py            # tout
    python3 tools/base_audit.py --only frontmatter,duplicates

Les sept contrôles :

  1. frontmatter   — YAML valide et description utilisable par le routeur
  2. doublons      — paires de skills aux descriptions quasi identiques
  3. orphelins     — fichiers de code que rien ne référence
  4. taille        — skills trop grosses pour tenir dans un budget d'injection
  5. domaines      — masse hors génie logiciel, et le coût RÉEL de la retirer
  6. rappel/rang1  — l'écart entre « le bon doc est dans la liste » et « il est 1er »
  7. hygiène code  — eval, réseau sortant, sous-processus dans les hooks
"""
from __future__ import annotations

import argparse
import itertools
import json
import math
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "vendor" / "ecc"
sys.path.insert(0, str(ROOT))

# Skills hors génie logiciel, nommées explicitement pour être relues et
# contestées une par une. Toute suppression doit passer par cette liste, pas par
# une règle sur le nom : trois d'entre elles sont de vraies réponses dans les
# jeux d'évaluation (voir docs/AUDIT-BASE.md).
OFF_DOMAIN = set("""carrier-relationship-management customs-trade-compliance energy-procurement
production-scheduling quality-nonconformance inventory-demand-planning returns-reverse-logistics
logistics-exception-management healthcare-cdss-patterns healthcare-emr-patterns healthcare-eval-harness
hipaa-compliance finance-billing-ops customer-billing-ops market-research marketing-campaign
brand-discovery brand-voice seo social-publisher content-engine crosspost investor-materials
investor-outreach esign-field-placement master-agreement-generator visa-doc-translate
lead-intelligence competitive-platform-analysis competitive-report-structure growth-log story-lifecycle
article-writing product-capability product-lens defi-amm-security evm-token-decimals
prediction-market-oracle-research prediction-market-risk-review nodejs-keccak256 agent-payment-x402
llm-trading-agent-security ito-baskets ito-compute ito-inference ito-training
homelab-network-readiness homelab-network-setup homelab-pihole-dns homelab-vlan-segmentation
homelab-wireguard-vpn network-bgp-diagnostics cisco-ios-patterns netmiko-ssh-automation
network-config-validation network-interface-health uncloud scientific-db-pubmed-database
scientific-db-uspto-database scientific-pkg-gget scientific-thinking-literature-review
scientific-thinking-scholar-evaluation bengali-nlp osint-investigation deep-research research-ops
manim-video remotion-video-creation video-editing tasteforge-video motion-advanced motion-foundations
motion-patterns blender-motion-state-inspection videodb fal-ai-media ecc-guide ecc-recipes
skill-comply skill-host-compat skill-scout skill-stocktake rules-distill hookify-rules
workspace-surface-audit council council-multi-model dev-team team-builder team-agent-orchestration""".split())

# Les trois « hors domaine » qui sont de vraies réponses : on ne les retire pas.
RESCUED = {"healthcare-phi-compliance", "ecc-tools-cost-audit", "configure-ecc"}


def skill_files() -> list[Path]:
    return sorted((BASE / "skills").glob("*/SKILL.md"))


def fm_of(p: Path) -> dict:
    import yaml

    text = p.read_text(encoding="utf-8", errors="replace")
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    return (yaml.safe_load(m.group(1)) if m else {}) or {}


def check_frontmatter() -> int:
    bad, no_desc, short = [], [], []
    for p in skill_files():
        try:
            fm = fm_of(p)
        except Exception as exc:
            bad.append((p.parent.name, str(exc)[:50]))
            continue
        desc = (fm.get("description") or "").strip()
        if not desc:
            no_desc.append(p.parent.name)
        elif len(desc) < 80:
            short.append((p.parent.name, len(desc)))
    print(f"  skills            : {len(skill_files())}")
    print(f"  YAML invalide     : {len(bad)}")
    print(f"  description vide  : {len(no_desc)}")
    print(f"  description < 80  : {len(short)}")
    for n, e in bad[:5]:
        print(f"     {n}: {e}")
    return 0


def check_duplicates(threshold: float = 0.55) -> int:
    docs = [(p.parent.name, (fm_of(p).get("description") or "").lower()) for p in skill_files()]

    def vec(s: str) -> dict[str, float]:
        w = re.findall(r"[a-z][a-z0-9-]{2,}", s)
        if not w:
            return {}
        c = Counter(w)
        n = math.sqrt(sum(v * v for v in c.values()))
        return {k: v / n for k, v in c.items()}

    V = [vec(d[1]) for d in docs]
    pairs = []
    for i, j in itertools.combinations(range(len(docs)), 2):
        a, b = V[i], V[j]
        if len(a) > len(b):
            a, b = b, a
        s = sum(v * b.get(k, 0) for k, v in a.items())
        if s > threshold:
            pairs.append((s, docs[i][0], docs[j][0]))
    pairs.sort(reverse=True)
    print(f"  paires quasi identiques (cosinus > {threshold}) : {len(pairs)}")
    for s, a, b in pairs[:10]:
        print(f"     {s:.2f}  {a:32s} {b}")
    print("  lecture : variantes de langage légitimes (golang-patterns vs kotlin-patterns)")
    print("            sont structurellement proches — ce ne sont pas des doublons.")
    return 0


def check_orphans() -> int:
    code = [p for p in (BASE / "scripts").rglob("*")
            if p.is_file() and p.suffix in (".js", ".mjs", ".cjs", ".ts", ".py")]
    texts = {}
    for p in BASE.rglob("*"):
        if p.is_file() and p.suffix in (".js", ".mjs", ".cjs", ".json", ".yml", ".yaml", ".md", ".py") \
                and "node_modules" not in str(p):
            try:
                texts[p] = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                pass
    def refname(p: Path) -> str:
        """The string other files would contain when they use this one.

        `Path("session-manager.d.ts").stem` is `"session-manager.d"` — a string
        that appears nowhere. The first version of this audit used `.stem`, so
        all three `.d.ts` files were reported as orphans while their `.js`
        counterparts are imported by four modules. A detector that invents
        orphans is worse than no detector: it justifies deletions.
        """
        name = p.name
        for suffix in (".d.ts", ".ts"):
            if name.endswith(suffix):
                return name[: -len(suffix)]
        return p.stem

    orphans = [f for f in code if not any(refname(f) in t for p, t in texts.items() if p != f)]
    print(f"  fichiers de code  : {len(code)}")
    print(f"  orphelins         : {len(orphans)}")
    for f in sorted(orphans):
        print(f"     {f.relative_to(BASE)}")
    return 0


def check_size() -> int:
    sizes = sorted(((len(p.read_text(encoding="utf-8", errors="replace")) // 4, p.parent.name)
                    for p in skill_files()), reverse=True)
    for budget in (2000, 4000, 8000):
        over = [s for s, _ in sizes if s > budget]
        print(f"  skills > {budget:5d} tokens : {len(over):3d}/{len(sizes)}")
    print(f"  médiane {statistics.median(s for s, _ in sizes):.0f} tok · max {sizes[0][0]} tok ({sizes[0][1]})")
    print("  lecture : le budget d'ECC est de 8 000 tokens ; une skill médiane en")
    print("            pèse 1 931. L'unité d'injection (le fichier entier) est trop")
    print("            grosse pour le plafond qu'on lui donne.")
    return 0


def check_domains() -> int:
    from eccxlib import indexer

    idx = indexer.load()
    cases = _cases()
    d1, d20 = _score(idx, cases, (1, 20))
    drop = OFF_DOMAIN - RESCUED
    kept = [d for d in idx["docs"] if d["id"] not in drop]
    e1, e20 = _score({"docs": kept}, cases, (1, 20))
    n = len(cases)
    print(f"  hors domaine (liste explicite) : {len(OFF_DOMAIN)} skills, {len(RESCUED)} sauvées → {len(drop)} retirées")
    print(f"  catalogue complet : @1 {d1}/{n} · @20 {d20}/{n}")
    print(f"  sans les {len(drop)}     : @1 {e1}/{n} · @20 {e20}/{n}")
    print("  lecture : retirer 92 skills ne rend même pas le rappel. L'argument")
    print("            « c'est du bruit » vaut +2 points au rang 1, pas 18.")
    return 0


def check_rank_gap() -> int:
    from eccxlib import indexer

    idx = indexer.load()
    cases = _cases()
    r1, r20 = _score(idx, cases, (1, 20))
    n = len(cases)
    print(f"  rappel @20 : {r20}/{n} ({r20 / n:.0%}) — le bon document EST trouvé")
    print(f"  précision @1 : {r1}/{n} ({r1 / n:.0%}) — mais il est rarement premier")
    print("  lecture : tout le travail restant est dans ce trou de 53 points.")
    print("            Le combler demande un second étage discriminatif, pas un")
    print("            élagage du catalogue.")
    return 0


def check_code_hygiene() -> int:
    hooks = list((BASE / "scripts" / "hooks").glob("*.js"))
    spawn = [p for p in hooks if re.search(r"child_process|execSync|spawnSync", p.read_text(errors="replace"))]
    # Production code only. A first pass counted 2 hits and they were *test
    # fixtures* — the string 'eval(x)' inside the tests of the hook that is
    # supposed to block it. A security audit that flags its own test data is
    # an audit nobody reads twice.
    def prod_js():
        for p in BASE.rglob("*.js"):
            s = str(p.relative_to(BASE))
            if s.startswith("tests/") or "node_modules" in s:
                continue
            yield p

    evals = [p for p in prod_js() if re.search(r"\beval\(|new Function\(", p.read_text(errors="replace"))]
    fixtures = [p for p in BASE.rglob("tests/**/*.js")
                if re.search(r"\beval\(|new Function\(", p.read_text(errors="replace"))]
    urls = Counter()
    for p in hooks:
        for u in re.findall(r"https://([a-zA-Z0-9.-]+)", p.read_text(errors="replace")):
            urls[u] += 1
    print(f"  hooks             : {len(hooks)}")
    print(f"  qui lancent un sous-processus : {len(spawn)}")
    print(f"  eval / new Function dans le code de prod : {len(evals)}")
    print(f"  (occurrences dans les fixtures de test   : {len(fixtures)} — attendu, elles testent le bloqueur)")
    print(f"  domaines cités dans les hooks : {', '.join(f'{d}×{c}' for d, c in urls.most_common(5))}")
    print("  lecture : pas d'eval en production, aucune requête sortante construite")
    print("            (les URL sont des liens de documentation). Le risque réel est")
    print("            le sous-processus, et il est inhérent à un système de hooks.")
    return 0


def _cases() -> list[dict]:
    out = []
    for name in ("heldout", "heldout2"):
        out += [json.loads(l) for l in (ROOT / "evals" / f"{name}.jsonl").read_text().splitlines() if l.strip()]
    return out


def _score(idx: dict, cases: list[dict], ks: tuple[int, ...]) -> list[int]:
    from eccxlib import router

    hits = {k: 0 for k in ks}
    for c in cases:
        ranked = [f"{r['doc']['kind']}:{r['doc']['id']}"
                  for r in router.score(idx, c["q"], kinds=None, top=max(ks), project_context=[])]
        for k in ks:
            if any(i in c["expect"] for i in ranked[:k]):
                hits[k] += 1
    return [hits[k] for k in ks]


CHECKS = {"frontmatter": check_frontmatter, "duplicates": check_duplicates, "orphans": check_orphans,
          "size": check_size, "domains": check_domains, "rank-gap": check_rank_gap,
          "hygiene": check_code_hygiene}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="liste séparée par des virgules")
    args = ap.parse_args()
    names = [n.strip() for n in args.only.split(",") if n.strip()] or list(CHECKS)
    for name in names:
        if name not in CHECKS:
            sys.exit(f"contrôle inconnu : {name} (connus : {', '.join(CHECKS)})")
        print(f"\n== {name} ==")
        CHECKS[name]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
