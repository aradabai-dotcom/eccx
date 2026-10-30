// Run ECC's *own* router on a jsonl of queries, so a claim about eccx can be
// compared against the thing ECC already ships.
//
//   node tools/ecc_router_bench.js evals/heldout.jsonl [repoRoot]
//
// Prints JSON: [{q, ranked: [ids...]}] on stdout, build stats on stderr.
// ECC routes skills only (292 entries) — comparison must restrict targets
// accordingly, see tools/bench_vs_ecc.py and docs/AUTONOMIE.md.
const fs = require('fs');
const path = require('path');

const file = process.argv[2];
// default: the base vendored into this repository, so the harness works
// without an external ~/ECC checkout.
const repoRoot = path.resolve(process.argv[3] || path.join(__dirname, '..', 'vendor', 'ecc'));
if (!file) { console.error('usage: node tools/ecc_router_bench.js QUERIES.jsonl [ECC_ROOT]'); process.exit(2); }
if (!fs.existsSync(path.join(repoRoot, 'scripts', 'lib', 'context-selection.js'))) {
  console.error(`pas de routeur ECC sous ${repoRoot} — ./tools/fetch_ecc.sh d'abord`);
  process.exit(2);
}

const { routingEntries } = require(path.join(repoRoot, 'scripts/lib/context-selection.js'));
const { buildRetrievalIndex, searchRetrieval } = require(path.join(repoRoot, 'scripts/lib/context-retrieval.js'));

const t0 = Date.now();
const entries = routingEntries({ repoRoot }).entries;
const index = buildRetrievalIndex(entries);
const buildMs = Date.now() - t0;

const out = [];
for (const line of fs.readFileSync(file, 'utf8').split('\n')) {
  if (!line.trim()) continue;
  const { q } = JSON.parse(line);
  const hits = searchRetrieval(index, q, { limit: 20 });
  out.push({ q, ranked: hits.map(h => h.id ?? h.entry?.id ?? h.name) });
}
console.error(`entrées=${entries.length} build=${buildMs}ms requêtes=${out.length}`);
console.log(JSON.stringify(out));
