"""Build stand-alone copies of web/index.html for a headless-Chrome render: fetch() is replaced by a stub that
streams one scripted final result whose `accuracy` is REAL evaluator output (+ the real question_review).
The page's own script is unchanged; the stub and an auto-ask are injected around it. Writes only into OUT."""
import json, sys
sys.path.insert(0, ".")
from tests.test_accuracy_ui import correct, evaluated, TWO_MISSING, ONE, PURCHASING
OUT = sys.argv[1]
page = open("web/index.html", encoding="utf-8").read()
cases = {
    "pass_100": (ONE, correct()),
    "fail_90": (TWO_MISSING, evaluated(TWO_MISSING, f"21 CFR 820.10(b)(2): {PURCHASING} [1]\nNot found in the available eCFR data: 21 CFR 820.99(z). The answer above covers only the provisions that were retrieved.")),
    "not_evaluated": (ONE, evaluated(ONE, "21 CFR 820.10(b)(2) obliges a maker to check bought-in goods [1].")),
}
for name, (q, acc) in cases.items():
    final = {"question": q, "answer": "Validated answer [1].", "model_called": True, "no_context": False,
             "citations": [{"index": 1, "label": "21 CFR 820.10(b)(2)", "url": "", "cited_in_answer": True}],
             "sources": [{"index": 1, "citation": "21 CFR 820.10(b)(2)", "corpus": "ecfr", "heading": "h", "method": "exact_cfr",
                          "score": 1, "url": "", "text": "body", "truncated": False}],
             "dropped_sources": 0, "notes": [], "grounding": None, "retrieval": {}, "query_type": "EXACT_CFR", "timings_ms": {},
             "adapter": {"id": ""}, "wall_seconds": 1.0, "server_timings_ms": {}, "accuracy": acc}
    stream = "\n".join(json.dumps(e) for e in [{"type": "start"}, {"type": "final", "result": final}]) + "\n"
    stub = ("<script>window.fetch = async (url) => url === '/api/config'\n"
            "  ? new Response(JSON.stringify({adapters: [], model_id: 'stub', device: 'cpu', snapshot_date: 'd', defaults: {}}))\n"
            f"  : new Response({json.dumps(stream)});</script>\n")
    auto = (f"<script>document.getElementById('q').value = {json.dumps(q)}; ask().then(() => "
            "document.body.setAttribute('data-done', '1'));</script>\n")
    html = page.replace("<script>", stub + "<script>", 1)
    i = html.rindex("</body>")
    open(f"{OUT}/{name}.html", "w", encoding="utf-8").write(html[:i] + auto + html[i:])
    print(name, q[:50], "| score", acc["question_review"]["live_check_score"], "| status", acc["question_review"]["label"])
