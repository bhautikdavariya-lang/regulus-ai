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
const server = { conversations: [], requests: [], streamPlan: [] };
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
async function fetchStub(url, opts = {}) {
  const method = (opts.method || "GET").toUpperCase();
  const body = opts.body ? JSON.parse(opts.body) : null;
  server.requests.push({ url, method, body });
  if (url === "/api/config") return json(200, { adapters: [], model_id: "m", device: "cpu", snapshot_date: "d", defaults: {} });
  if (url === "/api/conversations" && scenario === "nohistory") return json(503, { error: "conversation history is unavailable" });
  if (url === "/api/conversations" && method === "GET")
    return json(200, { conversations: server.conversations.map(({ messages, ...c }) => ({ ...c, message_count: messages.length })) });
  if (url === "/api/conversations" && method === "POST") {
    const c = conv(`conv-new-${server.conversations.length + 1}`, null, []);
    server.conversations.unshift(c);
    return json(201, { conversation: { ...c, messages: undefined } });
  }
  const m = url.match(/^\/api\/conversations\/(.+)$/);
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

const ctx = { document: { getElementById: el }, fetch: fetchStub, performance, setInterval, clearInterval, console,
              window: {}, TextDecoder, TextEncoder, AbortController, JSON, localStorage, crypto, isNaN, Date };
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
});

(async () => {
  if (scenario === "restore" || scenario === "switch") {
    server.conversations.push(conv("conv-aaaa-1111", "About Part 11", [
      { turn_id: "t-a1", role: "user", status: "ok", content: "What does Part 11 cover?" },
      { turn_id: "t-a1", role: "assistant", status: "ok", content: "Part 11 answer", result: result("What does Part 11 cover?", "A") },
    ]));
    server.conversations.push(conv("conv-bbbb-2222", "About Part 820", [
      { turn_id: "t-b1", role: "user", status: "ok", content: "What does Part 820 cover?" },
      { turn_id: "t-b1", role: "assistant", status: "error", content: "Request failed: model crashed" },
      { turn_id: "t-b2", role: "user", status: "ok", content: "Interrupted question?" },
    ]));
    if (scenario === "restore") localStorage.setItem("regulus.activeConversation", "conv-bbbb-2222");
  }
  vm.runInContext(script + "\n;this.chat = chat;", ctx);
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
  }
  process.stdout.write(JSON.stringify(out));
})().catch(e => { process.stderr.write(String(e && e.stack || e)); process.exit(1); });
