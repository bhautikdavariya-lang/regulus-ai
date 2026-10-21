"""Fetch official US Code (govinfo, most recent edition) sections of Title 21 as plain text.

usage: python -I fetch_usc.py OUTDIR "FDCA_LABEL=USC_SECTION" ...
e.g. "FDCA 910=387j"
"""
import hashlib, html, json, os, re, sys, time, urllib.request

LINK = "https://www.govinfo.gov/link/uscode/21/{sec}?type=usc&year=mostrecent&link-type=html"


def main():
    outdir = os.path.join(sys.argv[1], "usc_title21")
    os.makedirs(outdir, exist_ok=True)
    log = open(os.path.join(sys.argv[1], "usc_fetch_log.jsonl"), "a")
    for spec in sys.argv[2:]:
        label, sec = spec.split("=")
        req = urllib.request.Request(LINK.format(sec=sec), headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                raw = r.read()
                final = r.geturl()
        except Exception as e:  # noqa: BLE001
            log.write(json.dumps({"label": label, "usc": sec, "error": repr(e)}) + "\n")
            print("FAIL", spec, e)
            continue
        t = raw.decode("utf-8", "replace")
        t = re.sub(r"(?is)<(script|style).*?</\1>", "", t)
        t = re.sub(r"(?i)<br\s*/?>|</p>|</h\d>|</div>", "\n", t)
        t = re.sub(r"<[^>]+>", "", t)
        t = html.unescape(t)
        t = "\n".join(" ".join(l.split()) for l in t.splitlines())
        t = re.sub(r"\n{2,}", "\n", t).strip() + "\n"
        name = f"21usc{sec}.txt"
        hdr = f"SOURCE: {final}\nLABEL: {label} = 21 U.S.C. {sec}\n\n"
        open(os.path.join(outdir, name), "w").write(hdr + t)
        log.write(json.dumps({"label": label, "usc": sec, "url": final,
                              "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                              "html_sha256": hashlib.sha256(raw).hexdigest(), "file": name}) + "\n")
        print("ok", spec, final.rsplit("/", 1)[-1], len(t))


if __name__ == "__main__":
    main()
