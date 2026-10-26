// Run web/index.html's own <script> in CHAT mode against a scripted server, without a browser.
// Prints one JSON object describing what the page showed and what it sent.
//
//   node tests/chat_ui_harness.js <scenario>
//
// Scenarios: fresh (first question starts a conversation), restore (a refresh reopens the
// remembered conversation), switch (two conversations never mix), retry (a failed turn is retried
// with the SAME turn id), nohistory (history unavailable: the plain console, no conversation
// fields sent), double (a second send while one is in flight is ignored), stream (the bubble shows
// progress one network read at a time, then the final answer), stream_retry (a failed streamed
// attempt, then Retry: nothing of either draft is shown), stream_stop (Stop pressed mid-stream).
// A streamed attempt sends content-free "progress" events, as the server does, and also text
// "delta" events, as an older server did: the page must never show their text.
//
// Delete and the Evaluation view (tests/test_ui_dashboard.py): delete (another conversation is
// deleted after its confirm step), delete_cancel (the confirm step is cancelled: nothing is sent),
// delete_active (the open conversation is deleted: back to a new chat), delete_busy (the open
// conversation cannot be deleted while it is answering), delete_fail (the server refuses: the row
// stays), search (the list filter), dashboard / dashboard_empty / dashboard_unavailable (the
// Evaluation view with a summary, with no history, and with history unavailable), dashboard_open
// (a recent evaluation opens its conversation at its turn), theme (the theme button's cycle),
// evalcard (a restored conversation whose answers carry evaluations: the card under each answer),
// evaldelete (a conversation deleted while the Evaluation view is open: the view refreshes at once, and a recent
// row whose conversation is gone says so instead of failing silently), gone (the open conversation was deleted
// elsewhere: the next question starts a new one), badge / badge_match (the model badge names the model the worker
// reports, and the configured label only when it is that model), scrollkeep (Chat -> Evaluation -> Chat puts the
// conversation back where the reader left it, or at its end when it changed meanwhile), evalrace (a delete while the
// Evaluation view's first summary is still in flight: one more summary is fetched when it lands), evaldelete_active
// (the open conversation deleted from the Evaluation view: the focus goes to New chat, never the hidden composer),
// focuskeep (a list or dashboard redraw puts a keyboard user's focus back on the same button), drawer (a narrow
// screen: an open drawer makes the page behind it inert and takes the focus; Escape gives both back).
// /api/benchmark/summary serves the real data/reference/benchmark_summary_v1.json.
// Used by tests/test_chat_ui.py. tests/answer_ui_stream_harness.js covers the answer rendering.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const scenario = process.argv[2] || "fresh";
const html = fs.readFileSync(path.join(__dirname, "..", "web", "index.html"), "utf8");
const script = html.slice(html.lastIndexOf("<script>") + 8, html.lastIndexOf("</script>"));

// ---- a DOM just rich enough for the chat code: elements by id, classes, attributes
const els = {};
const el = id => (els[id] ||= (() => {
  const classes = new Set();
  let html = "";
  return {
    id, textContent: "", value: "", hidden: false, disabled: false, placeholder: "",
    get innerHTML() { return html; },
    set innerHTML(v) {            // like a browser: elements named in new markup are new elements
      html = String(v);
      for (const m of html.matchAll(/id="([^"]+)"([^>]*)>/g)) { delete els[m[1]]; if (/\bhidden\b/.test(m[2])) el(m[1]).hidden = true; }
    },
    onclick: null, attrs: {}, focused: 0, addEventListener() {}, focus() { this.focused += 1; },
    scrollIntoView() {}, setAttribute(k, v) { this.attrs[k] = v; },
    classList: { add: c => classes.add(c), remove: c => classes.delete(c), contains: c => classes.has(c),
                 toggle: (c, on) => (on ?? !classes.has(c)) ? classes.add(c) : classes.delete(c) },
    get className() { return [...classes].join(" "); },
  };
})());
const storage = new Map();
const localStorage = { getItem: k => (storage.has(k) ? storage.get(k) : null), setItem: (k, v) => storage.set(k, String(v)),
                       removeItem: k => storage.delete(k) };
let uuidN = 0;
const crypto = { randomUUID: () => `turn-0000-${String(++uuidN).padStart(4, "0")}` };

// ---- the scripted server
const server = { conversations: [], requests: [], streamPlan: [], deleted: new Set() };
const nowIso = () => new Date(Date.UTC(2026, 9, 13, 12, 0, server.requests.length)).toISOString();
const result = (question, n) => ({
  question, answer: `Validated answer ${n} [1].`, model_called: true, no_context: false,
  citations: [{ index: 1, label: "21 CFR 820.10(b)(2)", url: "https://example/1", cited_in_answer: true }],
  sources: [{ index: 1, citation: "21 CFR 820.10(b)(2)", corpus: "ecfr", heading: "h", method: "exact_cfr", score: 1,
              url: "https://example/1", text: "body", truncated: false }],
  dropped_sources: 0, notes: [], grounding: null, retrieval: {}, query_type: "EXACT_CFR", timings_ms: {},
  adapter: { id: "" }, wall_seconds: 1.0, server_timings_ms: {},
});
function conv(id, title, messages) { return { id, title, created_at: nowIso(), updated_at: nowIso(), messages }; }
function json(status, body) { return { ok: status < 400, status, json: async () => body }; }
function ndjson(events) {
  const bytes = new TextEncoder().encode(events.map(e => JSON.stringify(e) + "\n").join(""));
  let done = false;
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => done
    ? { value: undefined, done: true } : (done = true, { value: bytes, done: false }) }) } };
}
const snaps = [];
function stepwise(events, signal, stopAfterDeltas) {
  let i = 0, deltas = 0;
  const snap = () => snaps.push({ phase: (els.draftphase || {}).textContent || null,
                                  visible: el("thread").innerHTML + "\n" + el("out").innerHTML + "\n" + el("status").textContent,
                                  pending_in_thread: el("thread").innerHTML.includes('id="draftphase"') });
  return { ok: true, status: 200, body: { getReader: () => ({ read: async () => {
    snap();
    if (signal && signal.aborted) { const e = new Error("aborted"); e.name = "AbortError"; throw e; }
    if (stopAfterDeltas != null && deltas >= stopAfterDeltas) { el("stop").onclick(); const e = new Error("aborted"); e.name = "AbortError"; throw e; }
    if (i >= events.length) return { value: undefined, done: true };
    const ev = events[i++];
    if (ev.type === "delta") deltas += 1;
    return { value: new TextEncoder().encode(JSON.stringify(ev) + "\n"), done: false };
  } }) } };
}
let gate = null;   // "double": hold the first stream open until the second send has been tried
let sumGate = null;   // "evalrace": hold the first summary response (computed when asked) until it is released

// The Evaluation view's data: /api/evaluation/summary in the server's shape (regulus.conversations.evaluation_summary)
const bucket = (lo, counts = {}) => ({ label: lo === 100 ? "100" : `${lo}\u2013${lo + 9}`, lo, hi: lo === 100 ? 100 : lo + 9,
                                       pass: 0, fail: 0, not_evaluated: 0, ...counts });
const DIM_KEYS = [["question_relevance", "Answers the question"], ["substantive_correctness", "Substantive correctness"],
                  ["evidence_support", "Evidence support"], ["citation_correctness", "Citation correctness"],
                  ["fabrication_free", "Unsupported claims"], ["completeness", "Completeness"], ["scope_correct", "Scope"]];
const BASIS = "Live evaluations of answers stored in this server's history. Each is an evidence-based assessment of one answer; not the 300-question acceptance-test score.";
const SUMMARY = {
  version: 1, generated_at: "2026-10-23T16:20:00.000+00:00", basis: BASIS,
  turns: { answered: 36, assessed: 35, without_evaluation: 1, failed: 2, unreadable: 0, limit: 5000, truncated: false },
  status: { pass: 3, fail: 23, not_evaluated: 9, not_fully_evaluated: 2 },
  scores: { scored: 28, median: 15, min: 0, max: 100,
            buckets: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map(lo => bucket(lo, {
              0: { fail: 13, not_evaluated: 2 }, 10: { fail: 3 }, 30: { fail: 4 }, 40: { fail: 3 }, 100: { pass: 3 } }[lo])) },
  dimensions: { basis: 28, states: ["pass", "partial", "fail", "not_established", "not_applicable"],
                rows: DIM_KEYS.map(([dimension, label], i) => ({ dimension, label, pass: 20 - i, partial: i % 2, fail: i,
                                                                  not_established: 8 - i - (i % 2), not_applicable: 0, total: 28 })) },
  rubrics: { regulus_live_evidence_assessment_v2: 35 },
  recent: [
    { conversation_id: "conv-aaaa-1111", turn_id: "t-a1", question: "What does Part 11 cover?", status: "pass", label: "PASS",
      score: 100, explanation: "All seven checks passed against the retrieved evidence.", created_at: "2026-10-13T12:00:05.000Z" },
    { conversation_id: "conv-bbbb-2222", turn_id: "t-b1", question: "<img src=x onerror=alert(1)>", status: "fail", label: "FAIL",
      score: 40, explanation: "Completeness fail: 82.5(c) was not addressed in the answer.", created_at: "2026-10-13T12:00:04.000Z" },
    { conversation_id: "conv-bbbb-2222", turn_id: "t-b2", question: "Interrupted question?", status: "not_evaluated",
      label: "NOT FULLY EVALUATED", score: 5, explanation: "No check failed, but some could not be decided from the retrieved evidence.",
      created_at: "2026-10-13T12:00:03.000Z" },
  ],
};
const EMPTY_SUMMARY = {
  ...SUMMARY,
  turns: { answered: 0, assessed: 0, without_evaluation: 0, failed: 0, unreadable: 0, limit: 5000, truncated: false },
  status: { pass: 0, fail: 0, not_evaluated: 0, not_fully_evaluated: 0 },
  scores: { scored: 0, median: null, min: null, max: null, buckets: [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100].map(lo => bucket(lo)) },
  dimensions: { basis: 0, states: SUMMARY.dimensions.states,
                rows: DIM_KEYS.map(([dimension, label]) => ({ dimension, label, pass: 0, partial: 0, fail: 0, not_established: 0,
                                                               not_applicable: 0, total: 0 })) },
  rubrics: {}, recent: [],
};
const BENCHMARK = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "data", "reference", "benchmark_summary_v1.json"), "utf8"));
const UNAVAILABLE = scenario === "nohistory" || scenario === "dashboard_unavailable";

async function fetchStub(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  server.requests.push({ url, method, body });
  if (url === "/api/config") {
    if (scenario === "badge" || scenario === "badge_match")       // the server's shape: models[] holds the configured label
      return json(200, { adapters: [], model_id: scenario === "badge" ? "Qwen/Qwen3-1.7B" : "Qwen/Qwen3-4B-Instruct-2507",
                         dtype: "mlx-4bit-g128", device: "mlx", snapshot_date: "2026-10-01", defaults: {},
                         models: [{ id: "qwen3-4b-2507", label: "Qwen3-4B-Instruct-2507 (MLX 4-bit)", available: true }],
                         active_model: "qwen3-4b-2507" });
    return json(200, { adapters: [], model_id: "m", device: "cpu", snapshot_date: "d", defaults: {} });
  }
  if (url.startsWith("/api/evaluation/summary")) {
    if (UNAVAILABLE) return json(503, { error: "conversation history is unavailable on this server" });
    const s = scenario === "dashboard_empty" ? EMPTY_SUMMARY : SUMMARY;
    const reply = json(200, { summary: { ...s, recent: s.recent.filter(r => !server.deleted.has(r.conversation_id)) } });
    if (sumGate) { const g = sumGate; sumGate = null; await g; }
    return reply;
  }
  if (url === "/api/benchmark/summary") return json(200, { benchmark: BENCHMARK });
  if (url === "/api/conversations" && UNAVAILABLE) return json(503, { error: "conversation history is unavailable" });
  if (url === "/api/conversations" && method === "GET")
    return json(200, { conversations: server.conversations.map(({ messages, ...c }) => ({ ...c, message_count: messages.length })) });
  if (url === "/api/conversations" && method === "POST") {
    const c = conv(`conv-new-${server.conversations.length + 1}`, null, []);
    server.conversations.unshift(c);
    return json(201, { conversation: { ...c, messages: undefined } });
  }
  const m = url.match(/^\/api\/conversations\/(.+)$/);
  if (m && method === "DELETE") {
    if (scenario === "delete_fail") return json(500, { error: "disk full" });
    const id = decodeURIComponent(m[1]);
    const c = server.conversations.find(x => x.id === id);
    if (!c) return json(404, { error: "conversation not found" });
    server.conversations = server.conversations.filter(x => x.id !== id);
    server.deleted.add(id);
    return json(200, { deleted: id, messages_deleted: c.messages.length });
  }
  if (m) {
    const c = server.conversations.find(x => x.id === decodeURIComponent(m[1]));
    return c ? json(200, { conversation: c }) : json(404, { error: "conversation not found" });
  }
  if (url === "/api/ask/stream") {
    if (gate) await gate;
    const step = server.streamPlan.shift() || "ok";
    if (step === "error") return ndjson([{ type: "start" }, { type: "error", error: "model crashed mid-generation" }]);
    if (typeof step === "object") {                 // a streamed attempt: drafts first, then its outcome
      const lead = [{ type: "start" }, { type: "context", sources: [], no_context: false },
                    { type: "generation_started", max_new_tokens: 2048 },
                    ...step.deltas.flatMap((text, i) => [{ type: "progress", elapsed_ms: 500 * i }, { type: "delta", text }])];
      if (step.kind === "error") return stepwise([...lead, { type: "error", error: "model crashed mid-generation" }], opts.signal);
      if (step.kind === "stop") return stepwise(lead, opts.signal, step.deltas.length);
      const n = server.requests.filter(r => r.url === "/api/ask/stream").length;
      const r = result(body.question, n);
      return stepwise([...lead, { type: "generation_finished", generated_tokens: 9, finished: true }, { type: "final", result: r }], opts.signal);
    }
    const n = server.requests.filter(r => r.url === "/api/ask/stream").length;
    const r = result(body.question, n);
    if (body.conversation_id) {
      const c = server.conversations.find(x => x.id === body.conversation_id);
      if (!c) return json(404, { error: "conversation not found" });   // as serve_ui answers before streaming
      if (!c.messages.some(x => x.turn_id === body.turn_id && x.role === "user"))
        c.messages.push({ turn_id: body.turn_id, role: "user", status: "ok", content: body.question });
      c.messages = c.messages.filter(x => !(x.turn_id === body.turn_id && x.role === "assistant"));
      c.messages.push({ turn_id: body.turn_id, role: "assistant", status: "ok", content: r.answer, result: r });
      c.title = c.title || body.question;
      r.conversation = { id: c.id, turn_id: body.turn_id, saved: true };
    }
    return ndjson([{ type: "start" }, { type: "final", result: r }]);
  }
  return json(404, { error: "not found" });
}

// "drawer": a phone-width window (the sidebar is a drawer, the evidence panel an overlay); elements that know `inert`
const NARROW = scenario === "drawer";
const INERT_IDS = ["main", "sidebar", "topbar", "empty", "thread", "composer"];
if (NARROW) for (const id of INERT_IDS) el(id).inert = false;
const narrowWindow = { matchMedia: q => ({ matches: q === "(max-width: 899px)" || q === "(max-width: 1279px)",
                                           addEventListener() {} }) };
const ctx = { document: { getElementById: el, activeElement: null }, fetch: fetchStub, performance, setInterval,
              clearInterval, console, window: NARROW ? narrowWindow : {}, TextDecoder, TextEncoder, AbortController, JSON,
              localStorage, crypto, isNaN, Date };
vm.createContext(ctx);

const settle = () => new Promise(r => setTimeout(r, 0));
const click = (container, attr, value) => el(container).onclick({ target: { closest: sel =>
  sel === `button[data-${attr}]` ? { dataset: { [attr]: value } } : null } });
const streamBodies = () => server.requests.filter(r => r.url === "/api/ask/stream").map(r => r.body);
const state = () => ({
  chat_enabled: ctx.chat.enabled, active: ctx.chat.id, remembered: localStorage.getItem("regulus.activeConversation"),
  thread: el("thread").innerHTML, out: el("out").innerHTML, sidebar: el("convlist").innerHTML,
  app_class: el("app").className, q: el("q").value, streams: streamBodies(),
  posts: server.requests.filter(r => r.url === "/api/conversations" && r.method === "POST").length,
  toast: el("toast").textContent, evalbody: el("evalbody").innerHTML, convtitle: el("convtitle").textContent,
  requests: server.requests.map(r => r.method + " " + r.url),
  deletes: server.requests.filter(r => r.method === "DELETE").map(r => r.url),
  status: el("status").textContent, status_title: el("status").attrs.title ?? null, env: el("env").textContent,
  badge_title: el("modelbadge").attrs.title ?? null, announce: el("announce").textContent, q_focused: el("q").focused,
  summaries: server.requests.filter(r => r.url.startsWith("/api/evaluation/summary")).length,
});
const RESTORE_SETUP = ["restore", "delete", "delete_cancel", "delete_active", "delete_busy", "delete_fail", "search",
                       "evaldelete", "gone", "scrollkeep", "evalrace", "evaldelete_active", "focuskeep", "drawer"];
const DIM = (dimension, label, state, glyph, detail) => ({ dimension, label, state, glyph, detail, claim: "c", evidence: [] });
const evaluated = (question, review, dims) => ({ ...result(question, "E"), accuracy: {
  status: "evaluated", accuracy: review.live_check_score, rubric_id: "regulus_live_evidence_assessment_v2", dimensions: dims,
  question_review: { question, substantive_correctness: { state: "pass", label: "Pass", detail: "d" },
                     citation_correctness: { state: "pass", label: "Pass", detail: "d" }, basis: "b", ...review } } });
const SWITCH_SETUP = ["switch", "dashboard_open"];

(async () => {
  if (RESTORE_SETUP.includes(scenario) || SWITCH_SETUP.includes(scenario)) {
    server.conversations.push(conv("conv-aaaa-1111", "About Part 11", [
      { turn_id: "t-a1", role: "user", status: "ok", content: "What does Part 11 cover?" },
      { turn_id: "t-a1", role: "assistant", status: "ok", content: "Part 11 answer", result: result("What does Part 11 cover?", "A") },
    ]));
    server.conversations.push(conv("conv-bbbb-2222", "About Part 820", [
      { turn_id: "t-b1", role: "user", status: "ok", content: "What does Part 820 cover?" },
      { turn_id: "t-b1", role: "assistant", status: "error", content: "Request failed: model crashed" },
      { turn_id: "t-b2", role: "user", status: "ok", content: "Interrupted question?" },
    ]));
    if (RESTORE_SETUP.includes(scenario)) localStorage.setItem("regulus.activeConversation", "conv-bbbb-2222");
  }
  if (scenario === "evalcard") {
    const q1 = "What does 82.5 require for certification?", q2 = "Is 740.17 a warning statement?";
    server.conversations.push(conv("conv-cccc-3333", "Evaluations", [
      { turn_id: "t-c1", role: "user", status: "ok", content: q1 },
      { turn_id: "t-c1", role: "assistant", status: "ok", content: "x", result: evaluated(q1,
          { status: "fail", label: "FAIL", live_check_score: 40, explanation: "Completeness fail: 82.5(c) was not addressed in the answer." },
          [DIM("completeness", "Completeness", "partial", "\u26a0", "82.5(c) not addressed"), DIM("scope_correct", "Scope", "pass", "\u2713", "in scope")]) },
      { turn_id: "t-c2", role: "user", status: "ok", content: q2 },
      { turn_id: "t-c2", role: "assistant", status: "ok", content: "x", result: evaluated(q2,
          { status: "pass", label: "PASS", live_check_score: 100, explanation: "All checks passed." }, []) },
    ]));
    server.conversations[0].messages[3].result.accuracy.status = "evaluator_error";   // a PASS the page must refuse
    localStorage.setItem("regulus.activeConversation", "conv-cccc-3333");
  }
  vm.runInContext(script + "\n;this.chat = chat;this.dash = dash;", ctx);
  await settle(); await settle(); await settle();
  const out = { scenario, after_init: state() };

  if (scenario === "fresh" || scenario === "nohistory") {
    el("q").value = "What does 21 CFR 820.10(b)(2) require?";
    await ctx.ask();
    await settle();
    out.after_first = state();
    if (scenario === "fresh") {
      el("q").value = "And what about (b)(4)?";
      await ctx.ask();
      await settle();
      out.after_second = state();
    }
  } else if (scenario === "switch") {
    click("convlist", "id", "conv-aaaa-1111"); await settle(); await settle();
    out.after_a = state();
    click("convlist", "id", "conv-bbbb-2222"); await settle(); await settle();
    out.after_b = state();
  } else if (scenario === "retry") {
    server.streamPlan = ["error", "ok"];
    el("q").value = "What does 21 CFR 820.10(b)(2) require?";
    await ctx.ask();
    await settle();
    out.after_error = state();
    click("thread", "retry", ctx.chat.messages[0].turn_id);
    await settle(); await settle(); await settle();
    out.after_retry = state();
  } else if (scenario === "stream") {
    server.streamPlan = [{ kind: "ok", deltas: ["Any unexplained ", "discrepancy must be ", "thoroughly investigated."] }];
    el("q").value = "What does 21 CFR 211.192 require for discrepancies?";
    await ctx.ask(); await settle();
    out.snaps = snaps.splice(0);
    out.after = state();
  } else if (scenario === "stream_retry") {
    server.streamPlan = [{ kind: "error", deltas: ["OLD-DRAFT first attempt ", "partial text"] },
                         { kind: "ok", deltas: ["NEW-DRAFT ", "second attempt"] }];
    el("q").value = "What does 21 CFR 211.192 require?";
    await ctx.ask(); await settle();
    out.first_snaps = snaps.splice(0);
    out.after_error = state();
    click("thread", "retry", ctx.chat.messages[0].turn_id);
    await settle(); await settle(); await settle(); await settle();
    out.retry_snaps = snaps.splice(0);
    out.after_retry = state();
  } else if (scenario === "stream_stop") {
    server.streamPlan = [{ kind: "stop", deltas: ["Partial ", "draft words"] }];
    el("q").value = "What does 21 CFR 211.192 require?";
    await ctx.ask(); await settle();
    out.snaps = snaps.splice(0);
    out.after = state();
  } else if (scenario === "double") {
    let release; gate = new Promise(r => (release = r));
    el("q").value = "first";
    const first = ctx.ask();
    await settle();
    el("q").value = "second";
    await ctx.ask();                                   // ignored: one is already in flight
    release(); await first; await settle();
    out.after = state();
  } else if (scenario === "delete" || scenario === "delete_fail") {
    click("convlist", "del", "conv-aaaa-1111"); await settle();
    out.after_ask = state();
    click("convlist", "delok", "conv-aaaa-1111"); await settle(); await settle(); await settle();
    out.after = state();
  } else if (scenario === "delete_cancel") {
    click("convlist", "del", "conv-aaaa-1111"); await settle();
    out.after_ask = state();
    click("convlist", "delno", "conv-aaaa-1111"); await settle(); await settle();
    out.after = state();
  } else if (scenario === "delete_active") {
    click("convlist", "del", "conv-bbbb-2222"); await settle();
    out.after_ask = state();
    click("convlist", "delok", "conv-bbbb-2222"); await settle(); await settle(); await settle();
    out.after = state();
  } else if (scenario === "delete_busy") {
    let release; gate = new Promise(r => (release = r));
    el("q").value = "A question that is still being answered";
    const pending = ctx.ask();
    await settle();
    await ctx.deleteConversation(ctx.chat.id);       // refused: this conversation is answering
    click("convlist", "del", ctx.chat.id); await settle();
    out.during = state();
    release(); await pending; await settle(); await settle();
    out.after = state();
  } else if (scenario === "search") {
    el("convsearch").value = "820"; el("convsearch").oninput(); await settle();
    out.after_820 = state();
    el("convsearch").value = "  zzz "; el("convsearch").oninput(); await settle();
    out.after_zzz = state();
    el("convsearch").value = ""; el("convsearch").oninput(); await settle();
    out.after_clear = state();
  } else if (scenario === "dashboard" || scenario === "dashboard_empty" || scenario === "dashboard_unavailable") {
    ctx.setView("eval");
    await settle(); await settle(); await settle(); await settle();
    out.after = state();
    out.view_hidden = { chat: el("chatview").hidden, eval: el("evalview").hidden };
    if (scenario === "dashboard") {
      click("evalbody", "filter", "fail"); await settle();
      out.after_filter = state();
      ctx.setView("chat"); await settle();
      out.after_back = state();
      out.view_back = { chat: el("chatview").hidden, eval: el("evalview").hidden };
    }
  } else if (scenario === "dashboard_open") {
    ctx.setView("eval");
    await settle(); await settle(); await settle(); await settle();
    out.dash = state();
    click("evalbody", "open", "conv-aaaa-1111/t-a1");
    await settle(); await settle(); await settle();
    out.after = state();
    out.after.turn_focused = (els["turn-t-a1"] || {}).focused || 0;
    ctx.setView("eval"); await settle(); await settle(); await settle(); await settle();
    click("convlist", "id", "conv-bbbb-2222"); await settle(); await settle();
    out.after_sidebar = state();
  } else if (scenario === "evaldelete") {
    ctx.setView("eval");
    await settle(); await settle(); await settle(); await settle();
    out.dash = state();
    click("convlist", "del", "conv-aaaa-1111"); await settle();
    click("convlist", "delok", "conv-aaaa-1111");
    await settle(); await settle(); await settle(); await settle(); await settle();
    out.after = state();
    click("evalbody", "open", "conv-zzzz-9999/t-z1");               // a row whose conversation no longer exists
    await settle(); await settle(); await settle(); await settle();
    out.after_stale_open = state();
  } else if (scenario === "gone") {
    server.conversations = server.conversations.filter(c => c.id !== "conv-bbbb-2222");   // deleted in another tab
    el("q").value = "Asked in a deleted conversation";
    await ctx.ask(); await settle(); await settle();
    out.after_first = state();
    el("q").value = "Asked again";
    await ctx.ask(); await settle(); await settle();
    out.after_second = state();
  } else if (scenario === "scrollkeep") {
    const sc = el("scroll");
    Object.assign(sc, { scrollHeight: 2000, clientHeight: 500, scrollTop: 300 });   // a reader part-way up the thread
    ctx.setView("eval"); await settle(); await settle(); await settle(); await settle();
    sc.scrollTop = 0;                                    // what a browser does to a display:none scroller
    ctx.setView("chat");
    out.kept = sc.scrollTop;
    ctx.setView("eval"); await settle();
    sc.scrollTop = 0;
    ctx.renderThread();                                  // the thread changed while hidden (an answer arrived)
    ctx.setView("chat");
    out.changed = sc.scrollTop;
  } else if (scenario === "evalrace") {
    let release; sumGate = new Promise(r => (release = r));
    ctx.setView("eval"); await settle();                    // the first summary is in flight ...
    await ctx.deleteConversation("conv-aaaa-1111");          // ... when a conversation is deleted
    await settle();
    out.during = state();
    release();
    for (let i = 0; i < 8; i += 1) await settle();
    out.after = state();
  } else if (scenario === "evaldelete_active") {
    ctx.setView("eval");
    await settle(); await settle(); await settle(); await settle();
    const q0 = el("q").focused, n0 = el("newchat").focused;
    click("convlist", "del", "conv-bbbb-2222"); await settle();
    click("convlist", "delok", "conv-bbbb-2222");
    await settle(); await settle(); await settle(); await settle(); await settle();
    out.after = { ...state(), q_focus_delta: el("q").focused - q0, newchat_focus_delta: el("newchat").focused - n0 };
  } else if (scenario === "focuskeep") {
    const refocused = [];
    const button = (k, v) => ({ getAttribute: a => (a === k ? v : null) });
    const watch = (id, b) => Object.assign(el(id), { contains: x => x === b,
                                                      querySelector: sel => ({ focus() { refocused.push(sel); } }) });
    const row = button("data-id", "conv-aaaa-1111");
    watch("convlist", row);
    ctx.document.activeElement = row;                        // a keyboard user on a row when the list is redrawn
    await ctx.refreshList();
    out.list = refocused.splice(0);
    ctx.setView("eval"); await settle(); await settle(); await settle(); await settle();
    const open = button("data-open", "conv-bbbb-2222/t-b1");
    watch("evalbody", open);
    ctx.document.activeElement = open;                       // ... and on a recent evaluation when the dashboard reloads
    await ctx.loadDashboard(true, true);
    out.dash = refocused.splice(0);
  } else if (scenario === "drawer") {
    const inert = () => Object.fromEntries(INERT_IDS.map(id => [id, el(id).inert]));
    const focus = () => ({ newchat: el("newchat").focused, sidetoggle: el("sidetoggle").focused,
                           evclose: el("evclose").focused, evtoggle: el("evtoggle").focused, q: el("q").focused });
    const escape = () => ctx.onKey({ key: "Escape", preventDefault() {} });
    ctx.toggleSidebar();
    out.side_open = { inert: inert(), focus: focus(), expanded: el("sidetoggle").attrs["aria-expanded"] };
    escape();
    out.side_closed = { inert: inert(), focus: focus(), expanded: el("sidetoggle").attrs["aria-expanded"] };
    ctx.setEvidence(true);
    out.ev_open = { inert: inert(), focus: focus() };
    escape();
    out.ev_closed = { inert: inert(), focus: focus() };
    ctx.setView("eval"); await settle(); await settle(); await settle(); await settle();
    ctx.toggleSidebar();                                     // the drawer, opened on the Evaluation view ...
    out.eval_side_open = { inert: inert(), focus: focus() };
    click("convlist", "del", "conv-bbbb-2222"); await settle();
    click("convlist", "delok", "conv-bbbb-2222");            // ... deletes the open conversation: the drawer closes
    await settle(); await settle(); await settle(); await settle(); await settle();
    out.eval_deleted = { ...state(), inert: inert(), focus: focus() };
  } else if (scenario === "badge" || scenario === "badge_match") {
    out.after = state();
  } else if (scenario === "theme") {
    out.themes = [];
    for (let i = 0; i < 3; i += 1) { ctx.cycleTheme(); out.themes.push(localStorage.getItem("regulus.theme")); }
    out.theme_label = el("themetoggle").attrs["aria-label"];
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
