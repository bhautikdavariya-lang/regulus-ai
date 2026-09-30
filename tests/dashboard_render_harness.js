// Render the real dashboard page against a live API, without a browser.
//
//   node tests/dashboard_render_harness.js <base-url> <route> [<route> ...]
//
// Loads web/dashboard.html's own <script>, gives it a minimal DOM and a
// fetch bound to <base-url>, boots it, then visits each hash route and prints
// one JSON object: {route: {text, nav, errors}}. The page code runs unmodified; the
// shim only implements what that code touches. Used by
// tests/test_observatory_ui.py and for real-data verification.
"use strict";
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const [base, ...routes] = process.argv.slice(2);

class Node_ {
  constructor(tag) { this.tagName = tag; this.children = []; this.attrs = {}; this.listeners = {}; this._text = null;
                     this.style = {}; this.dataset = {}; this.className = ""; this.value = ""; this.disabled = false; }
  appendChild(c) { this.children.push(c); c.parent = this; return c; }
  append(...cs) { for (const c of cs) this.appendChild(c); }
  setAttribute(k, v) { this.attrs[k] = String(v); if (k.startsWith("data-")) this.dataset[k.slice(5)] = String(v);
                       if (k === "id") this.id = String(v); if (k === "value") this.value = String(v); }
  getAttribute(k) { return this.attrs[k] ?? null; }
  addEventListener(t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); }
  set innerHTML(v) { this.children = []; this._text = String(v).replace(/<[^>]*>/g, ""); }
  get innerHTML() { return ""; }
  set textContent(v) { this.children = []; this._text = String(v); }
  get textContent() { return (this._text || "") + this.children.map(c => c.textContent).join(" "); }
  get options() { return this.children.filter(c => c.tagName === "option"); }
  querySelector(sel) { return this.querySelectorAll(sel)[0] || null; }
  querySelectorAll(sel) {
    const out = [], walk = (n) => { for (const c of n.children || []) { if (match(c, sel)) out.push(c); walk(c); } };
    walk(this); return out;
  }
  get offsetWidth() { return 0; } get offsetHeight() { return 0; }
  getBoundingClientRect() { return {left:0, top:0, width:720, height:260}; }
  setAttributeNS(_ns, k, v) { this.setAttribute(k, v); }
}
class Text_ { constructor(t) { this.t = t; } get textContent() { return this.t; } }
function match(n, sel) {
  if (!(n instanceof Node_)) return false;
  if (sel.startsWith("#")) return n.id === sel.slice(1);
  if (sel === "input:checked") return n.tagName === "input" && n.attrs.checked;
  return n.tagName === sel;
}

const html = fs.readFileSync(path.join(__dirname, "..", "web", "dashboard.html"), "utf-8");
const script = html.slice(html.indexOf("<script>") + 8, html.lastIndexOf("</script>"));
const root = new Node_("body");
for (const id of ["head-sub", "nav", "alerts", "view", "tip", "theme", "refresh"]) {
  const n = new Node_("div"); n.setAttribute("id", id); root.appendChild(n);
}
const errors = [];
const location = { hash: "" };
const context = {
  document: {
    createElement: (t) => new Node_(t), createElementNS: (_ns, t) => new Node_(t), createTextNode: (t) => new Text_(t),
    querySelector: (s) => root.querySelector(s), documentElement: new Node_("html"),
  },
  location, URLSearchParams, Date, Math, JSON, Promise, Object, Array, String, Number, Set, Map, Error, isNaN,
  console: { log() {}, error: (...a) => errors.push(a.join(" ")) },
  window: { addEventListener() {}, innerWidth: 1200, innerHeight: 900 },
  setInterval() { return 0; }, setTimeout: (f) => f(), alert: (m) => errors.push("alert: " + m),
  fetch: (p, o) => fetch(base + p, o),
};
vm.createContext(context);

(async () => {
  // define everything, but replace the final boot() call so we control it
  vm.runInContext(script.replace(/\nboot\(\);\s*$/, "\n"), context);
  await vm.runInContext("load()", context);
  // the primary navigation, as boot() would build it
  vm.runInContext("if (typeof buildNav === 'function') buildNav();", context);
  const out = {};
  for (const route of routes) {
    location.hash = route;
    try { await vm.runInContext("render()", context); } catch (e) { errors.push(String(e)); }
    const view = root.querySelector("#view");
    // which primary navigation item the page marked as active
    const nav = root.querySelector("#nav").children.filter(c => c.className === "on").map(c => c.textContent.trim());
    out[route] = { text: view.textContent.replace(/\s+/g, " ").trim(), nav, errors: errors.splice(0) };
  }
  process.stdout.write(JSON.stringify(out));
})().catch((e) => { process.stdout.write(JSON.stringify({ __fatal__: String(e && e.stack || e) })); process.exit(1); });
