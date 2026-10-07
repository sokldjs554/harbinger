// 파이썬(features/text.py)과 브라우저 포트(console/memo.js)의 메모 분석이 한 건도 다르지 않은지 비교한다.
//   node scripts/check_memo_parity.cjs lexicon.json cases.json   (cases = 파이썬이 만든 기대 결과 배열)
const fs = require("node:fs");
const path = require("node:path");
const M = require(path.join(__dirname, "..", "src", "harbinger", "console", "memo.js"));
const lex = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const cases = JSON.parse(fs.readFileSync(process.argv[3], "utf8"));
const ctx = M.build(lex);
const keys = ["length", "lazy", "n_groups", "weak_hits", "strong_hits", "weak_score", "strong_score"];
let bad = 0;
for (const exp of cases) {
  const got = M.analyze(ctx, exp.memo);
  const diffs = [];
  for (const k of keys) if (JSON.stringify(got[k]) !== JSON.stringify(exp[k])) diffs.push(`${k}: py=${JSON.stringify(exp[k])} js=${JSON.stringify(got[k])}`);
  if (JSON.stringify(got.groups.map((g) => g.id)) !== JSON.stringify(exp.groups.map((g) => g.id))) diffs.push("groups");
  const seg = (a) => JSON.stringify(a.segments.map((s) => [s.text, s.kind, s.group ?? null]));
  if (seg(got) !== seg(exp)) diffs.push(`segments: py=${seg(exp)} js=${seg(got)}`);
  if (diffs.length) { bad++; if (bad <= 5) console.error(`MISMATCH ${JSON.stringify(exp.memo)}\n  ` + diffs.join("\n  ")); }
}
console.log(JSON.stringify({ cases: cases.length, mismatches: bad }));
process.exit(bad ? 1 : 0);
