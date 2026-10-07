/* 메모 분석 — features/text.py 의 JS 포트. 렉시콘은 서버(/v1/text/lexicon)와 같은 것을 받아 쓴다.
 * 점수와 구간 나누기 규칙이 파이썬과 어긋나면 데모가 모델과 다른 방식으로 메모를 읽는 셈이므로,
 * tests/test_memo_parity.py 가 이 파일을 node 로 불러 파이썬 결과와 한 건씩 비교한다.
 * 브라우저에서는 window.HarbingerMemo, node 에서는 module.exports 로 노출된다. */
(function (root, factory) {
  if (typeof module === "object" && module.exports) module.exports = factory();
  else root.HarbingerMemo = factory();
})(typeof self !== "undefined" ? self : this, function () {
  const PRIORITY = { strong: 0, weak: 1, symptom: 2 };
  const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const alt = (words) => new RegExp(words.map(esc).join("|"), "g");

  function build(lex) {
    const kwGroup = {};
    for (const [g, spec] of Object.entries(lex.symptom_groups)) for (const kw of spec.keywords) if (!(kw in kwGroup)) kwGroup[kw] = g;
    return {
      lex,
      weakRe: alt(lex.weak_modifiers),
      strongRe: alt(lex.strong_modifiers),
      symRe: alt(lex.symptom_keywords),
      lazy: new Set(lex.lazy_memos),
      kwGroup,
    };
  }

  function all(re, text) {
    re.lastIndex = 0;
    const out = [];
    let m;
    while ((m = re.exec(text)) !== null) {
      out.push({ start: m.index, end: m.index + m[0].length, text: m[0] });
      if (m[0].length === 0) re.lastIndex++;
    }
    return out;
  }

  function segments(ctx, text) {
    const spans = [];
    for (const [kind, re] of [["strong", ctx.strongRe], ["weak", ctx.weakRe], ["symptom", ctx.symRe]])
      for (const m of all(re, text)) spans.push({ start: m.start, end: m.end, prio: PRIORITY[kind], kind });
    spans.sort((a, b) => a.start - b.start || a.prio - b.prio || (b.end - b.start) - (a.end - a.start));
    const out = [];
    let pos = 0;
    for (const s of spans) {
      if (s.start < pos) continue;
      if (s.start > pos) out.push({ text: text.slice(pos, s.start), kind: null });
      const piece = { text: text.slice(s.start, s.end), kind: s.kind };
      if (s.kind === "symptom") piece.group = ctx.kwGroup[piece.text] ?? null;
      out.push(piece);
      pos = s.end;
    }
    if (pos < text.length) out.push({ text: text.slice(pos), kind: null });
    return out;
  }

  function analyze(ctx, memo) {
    const text = memo || "";
    const groups = [];
    for (const [g, spec] of Object.entries(ctx.lex.symptom_groups)) if (spec.keywords.some((k) => text.includes(k))) groups.push({ id: g, label: spec.label });
    const weak = all(ctx.weakRe, text).map((m) => m.text);
    const strong = all(ctx.strongRe, text).map((m) => m.text);
    return {
      memo: text,
      length: [...text].length,
      lazy: ctx.lazy.has(text.trim()),
      n_groups: groups.length,
      groups,
      weak_hits: weak,
      strong_hits: strong,
      weak_score: weak.length > 0 ? groups.length : 0,
      strong_score: strong.length > 0 ? groups.length : 0,
      segments: segments(ctx, text),
    };
  }

  /* 모델이 이 메모를 어떻게 다루는지 한 문장 */
  function reading(a) {
    if (!a.memo.trim()) return "메모가 비어 있습니다 — 모델은 이 점검에서 텍스트 신호를 얻지 못합니다.";
    if (a.lazy) return "형식적 메모입니다. 텍스트 신호가 없고, 같은 점검자가 이런 메모를 자주 남기면 그 점검자의 ‘양호’는 증거 가중치가 낮아집니다.";
    if (a.strong_score > 0) return "강신호입니다(심함·긴급·수리 등). 체크리스트 판정과 함께 위험도를 크게 올립니다. 다만 불량으로 기록되면 곧 수리로 이어지므로 ‘조치되지 않은 고장’ 확률은 오히려 내려갈 수 있습니다.";
    if (a.weak_score > 0) return "약신호입니다(약간·미세·간헐 등). 체크리스트가 ‘양호’여도 모델은 이 설비를 주시합니다 — 이 프로젝트가 메모를 읽는 이유입니다.";
    if (a.n_groups > 0) return "증상은 언급했지만 강도 표현이 없습니다. 증상군 수만 피처로 쓰입니다.";
    return "증상 언급이 없습니다. 텍스트 피처가 모두 0 입니다.";
  }

  return { build, analyze, segments, reading };
});
