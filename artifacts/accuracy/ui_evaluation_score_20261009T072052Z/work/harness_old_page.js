// Run web/index.html's own <script> against a scripted /api/ask/stream response,
// without a browser. Prints one JSON object describing what the page showed.
//
//   node tests/answer_ui_stream_harness.js <scenario>
//
// Scenarios: normal (events split across odd network chunk boundaries),
// error (an "error" event after some drafts), truncated (the connection closes
// with no final event), accuracy_scored / accuracy_unknown / accuracy_failed /
// accuracy_off (the answer-accuracy indicator in each of its states).
// Used by tests/test_streaming_ui.py and tests/test_accuracy_ui.py.
//
//   node tests/answer_ui_stream_harness.js file <payload.json>
//
// Scenario "file" merges payload.result into the final result and types
// payload.page_question into the question box: real evaluator output, built in
// Python, rendered by the page (tests/test_accuracy_ui.py). With payload.sequence
// (a list of {page_question, result}) the page asks each in turn in ONE session
// and the output adds `finals`, the evaluation block after each answer.
//
//   node tests/answer_ui_stream_harness.js scores <values.json>
//
// Calls the page's own evaluationScore() and renderEvaluation() on each value,
// including values JSON cannot carry ("__NaN__", "__Infinity__", "__-Infinity__",
// "__undefined__"), and prints what each renders.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scenario = process.argv[2] || "normal";
const html = fs.readFileSync("/Users/sensussoftsoftware/Desktop/Prachi Patel/Regulus AI.nosync/artifacts/accuracy/ui_evaluation_score_20261009T072052Z/snapshot_before/index.html", "utf8");
const script = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));

const els = {};
const el = id => (els[id] ||= { id, innerHTML: "", textContent: "", value: "", hidden: false, disabled: false,
  onclick: null, addEventListener() {}, focus() {}, checked: false });
const snapshots = [];

const final = {
  question: "q", answer: "Validated answer [1].", model_called: true, no_context: false,
  citations: [{ index: 1, label: "21 CFR 820.10(b)(2)", url: "https://example/1", cited_in_answer: true }],
  sources: [{ index: 1, citation: "21 CFR 820.10(b)(2)", corpus: "ecfr", heading: "h", method: "exact_cfr", score: 1,
              url: "https://example/1", text: "body", truncated: false }],
  dropped_sources: 0, notes: [], grounding: null, retrieval: {}, query_type: "EXACT_CFR", timings_ms: {},
  adapter: { id: "" }, wall_seconds: 1.0, stream: { deltas: 3 },
  server_timings_ms: { accuracy_ms: 1.4 },
};

// The accuracy payloads, as regulus.accuracy.AccuracyAssessment.to_dict() emits them.
const DIM = (dimension, label, state, glyph, detail) => ({ dimension, label, state, glyph, detail, claim: "c", evidence: [] });
const ACCURACY = {
  accuracy_scored: {
    status: "evaluated", accuracy: 90, reason: "Completeness: one requested provision was not retrieved.",
    rubric_id: "regulus_live_evidence_assessment_v1", basis: "Based on the authoritative regulatory evidence retrieved for this answer.",
    not_the_benchmark: "An evidence-based assessment of this one answer. It is not the 300-question acceptance-test score.",
    deductions: [{ dimension: "completeness", state: "partial", points: 10 }],
    dimensions: [
      DIM("substantive_correctness", "Substantive correctness", "pass", "\u2713", "verbatim"),
      DIM("evidence_support", "Evidence support", "pass", "\u2713", "verbatim"),
      DIM("citation_correctness", "Citation correctness", "pass", "\u2713", "resolves"),
      DIM("fabrication_free", "Unsupported claims", "pass", "\u2713", "none"),
      DIM("completeness", "Completeness", "partial", "\u26a0", "820.99(z) was not retrieved"),
      DIM("scope_correct", "Scope", "pass", "\u2713", "in scope"),
    ],
  },
  accuracy_unknown: {
    status: "unable_to_determine", accuracy: null,
    reason: "Not enough can be established from the authoritative evidence to score this answer.",
    rubric_id: "regulus_live_evidence_assessment_v1", basis: "b", not_the_benchmark: "n", deductions: [],
    dimensions: [DIM("substantive_correctness", "Substantive correctness", "not_established", "?", "paraphrase")],
  },
  accuracy_failed: {
    status: "evaluated", accuracy: 0, reason: "Unsupported claims: figure(s) not found in any supplied source: 45",
    rubric_id: "regulus_live_evidence_assessment_v1", basis: "b", not_the_benchmark: "n",
    deductions: [{ dimension: "fabrication_free", state: "fail", points: 100 }],
    dimensions: [DIM("fabrication_free", "Unsupported claims", "fail", "\u2717", "figure 45 is in no source")],
  },
};
if (ACCURACY[scenario]) final.accuracy = ACCURACY[scenario];
const fromFile = scenario === "file" ? JSON.parse(fs.readFileSync(process.argv[3], "utf8")) : null;
if (fromFile) Object.assign(final, fromFile.result || {});
const SPECIAL = { __NaN__: NaN, __Infinity__: Infinity, "__-Infinity__": -Infinity, __undefined__: undefined };
const steps = fromFile && Array.isArray(fromFile.sequence)
  ? fromFile.sequence.map(st => ({ question: st.page_question, final: { ...final, ...(st.result || {}) } })) : null;
const lines = [
  { type: "start" },
  { type: "context", sources: [{ index: 1, citation: "21 CFR 820.10(b)(2)" }], no_context: false },
  { type: "generation_started", max_new_tokens: 256 },
  { type: "delta", text: "Draft " }, { type: "delta", text: "answer " }, { type: "delta", text: "[9]." },
  { type: "generation_finished", generated_tokens: 3, finished: true },
];
function chunksFor(finalResult) {
  const all = lines.slice();
  if (scenario !== "error" && scenario !== "truncated") all.push({ type: "final", result: finalResult });
  if (scenario === "error") all.push({ type: "error", error: "model crashed mid-generation" });
  const payload = all.map(l => JSON.stringify(l) + "\n").join("");
  // split at deliberately awkward places, including inside a JSON line and a multi-byte-safe boundary
  const cuts = [7, 40, 41, 90, 130, 131];
  // and a cut in the middle of every later line, so each delta arrives in its own read, split mid-JSON
  let pos = 0;
  for (const l of all.map(x => JSON.stringify(x) + "\n")) { if (pos > 131) cuts.push(pos + Math.floor(l.length / 2)); pos += l.length; }
  cuts.sort((a, b) => a - b);
  const out = [];
  let last = 0;
  for (const c of cuts.filter(c => c < payload.length)) { out.push(payload.slice(last, c)); last = c; }
  out.push(payload.slice(last));
  return out;
}
let chunks = chunksFor(final);

const encoder = new TextEncoder();
const fetchStub = async (url) => {
  if (url === "/api/config") return { json: async () => ({ adapters: [], model_id: "m", device: "cpu", snapshot_date: "d", defaults: {} }) };
  let i = 0;
  return {
    ok: true, status: 200,
    body: { getReader: () => ({ read: async () => {
      snapshots.push(els.out ? els.out.innerHTML : "");
      return i < chunks.length ? { value: encoder.encode(chunks[i++]), done: false } : { value: undefined, done: true };
    } }) },
  };
};
const ctx = { document: { getElementById: el }, fetch: fetchStub, performance, setInterval, clearInterval,
              console, window: {}, TextDecoder, TextEncoder, AbortController, JSON };
vm.createContext(ctx);
vm.runInContext(script, ctx);
el("q").value = (fromFile && fromFile.page_question) || "What does 21 CFR 820.10(b)(2) require?";
(async () => {
  if (scenario === "scores") {
    const values = JSON.parse(fs.readFileSync(process.argv[3], "utf8")).map(v => (v in SPECIAL ? SPECIAL[v] : v));
    console.log(JSON.stringify(values.map(v => {
      const e = { status: "fail", label: "FAIL", live_check_score: v, explanation: "x", basis: "b" };
      return { value: String(v), score: ctx.evaluationScore(e), html: ctx.renderEvaluation(e, null) };
    })));
    return;
  }
  const finals = [];
  for (const st of steps || []) {
    el("q").value = st.question;
    chunks = chunksFor(st.final);
    await ctx.ask();
    finals.push(els.out.innerHTML);
  }
  if (!steps) await ctx.ask();
  const out = els.out.innerHTML;
  console.log(JSON.stringify({
    draft_seen: snapshots.some(s => s.includes("draft · generating") && s.includes("Draft answer")),
    final_out: out, status: els.status.textContent, stop_hidden: els.stop.hidden, ask_disabled: els.ask.disabled,
    answer_shown: out.includes("Validated answer [1]."), finals,
  }));
})();
