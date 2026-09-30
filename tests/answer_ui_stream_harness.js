// Run web/index.html's own <script> against a scripted /api/ask/stream response,
// without a browser. Prints one JSON object describing what the page showed.
//
//   node tests/answer_ui_stream_harness.js <scenario>
//
// Scenarios: normal (events split across odd network chunk boundaries),
// error (an "error" event after some drafts), truncated (the connection closes
// with no final event). Used by tests/test_streaming_ui.py.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scenario = process.argv[2] || "normal";
const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
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
};
const lines = [
  { type: "start" },
  { type: "context", sources: [{ index: 1, citation: "21 CFR 820.10(b)(2)" }], no_context: false },
  { type: "generation_started", max_new_tokens: 256 },
  { type: "delta", text: "Draft " }, { type: "delta", text: "answer " }, { type: "delta", text: "[9]." },
  { type: "generation_finished", generated_tokens: 3, finished: true },
];
if (scenario === "normal") lines.push({ type: "final", result: final });
if (scenario === "error") lines.push({ type: "error", error: "model crashed mid-generation" });
const payload = lines.map(l => JSON.stringify(l) + "\n").join("");
// split at deliberately awkward places, including inside a JSON line and a multi-byte-safe boundary
const cuts = [7, 40, 41, 90, 130, 131];
// and a cut in the middle of every later line, so each delta arrives in its own read, split mid-JSON
let pos = 0;
for (const l of lines.map(x => JSON.stringify(x) + "\n")) { if (pos > 131) cuts.push(pos + Math.floor(l.length / 2)); pos += l.length; }
cuts.sort((a, b) => a - b);
const chunks = [];
let last = 0;
for (const c of cuts.filter(c => c < payload.length)) { chunks.push(payload.slice(last, c)); last = c; }
chunks.push(payload.slice(last));

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
el("q").value = "What does 21 CFR 820.10(b)(2) require?";
(async () => {
  await ctx.ask();
  const out = els.out.innerHTML;
  console.log(JSON.stringify({
    draft_seen: snapshots.some(s => s.includes("draft · generating") && s.includes("Draft answer")),
    final_out: out, status: els.status.textContent, stop_hidden: els.stop.hidden, ask_disabled: els.ask.disabled,
  }));
})();
