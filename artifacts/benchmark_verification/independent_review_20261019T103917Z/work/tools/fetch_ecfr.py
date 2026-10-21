"""Fetch official eCFR text for Title 21 parts as of a date and save plain text.

usage: python -I fetch_ecfr.py OUTDIR DATE PART [PART ...]
Writes OUTDIR/ecfr_<DATE>/part-<PART>.txt and .xml (raw), and appends to OUTDIR/ecfr_fetch_log.jsonl.
Each section begins with a line '=== § <id> <heading>' so it can be grepped.
"""
import hashlib, json, os, sys, time, urllib.request, gzip
from xml.etree import ElementTree as ET

API = "https://www.ecfr.gov/api/versioner/v1/full/{date}/title-21.xml?part={part}"


def fetch(url):
    req = urllib.request.Request(url, headers={"Accept-Encoding": "gzip", "User-Agent": "regulus-benchmark-verification/1.0"})
    with urllib.request.urlopen(req, timeout=180) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
    return data


def text_of(el):
    return " ".join("".join(el.itertext()).split())


def render(root):
    lines = []
    for el in root.iter():
        tag = el.tag
        typ = el.get("TYPE", "")
        if tag.startswith("DIV") and typ in ("PART", "SUBPART", "SUBJGRP"):
            head = el.find("HEAD")
            lines.append("")
            lines.append(f"##### {typ} {el.get('N','')}: {text_of(head) if head is not None else ''}")
        elif tag.startswith("DIV") and typ == "SECTION":
            head = el.find("HEAD")
            lines.append("")
            lines.append(f"=== § {el.get('N','')} | {text_of(head) if head is not None else ''}")
            for child in el:
                if child.tag == "HEAD":
                    continue
                t = text_of(child)
                if t:
                    lines.append(t)
        elif tag.startswith("DIV") and typ == "APPENDIX":
            head = el.find("HEAD")
            lines.append("")
            lines.append(f"=== APPENDIX {el.get('N','')} | {text_of(head) if head is not None else ''}")
            for child in el:
                if child.tag != "HEAD":
                    t = text_of(child)
                    if t:
                        lines.append(t)
    return "\n".join(lines) + "\n"


def main():
    outdir, date, parts = sys.argv[1], sys.argv[2], sys.argv[3:]
    d = os.path.join(outdir, f"ecfr_{date}")
    os.makedirs(d, exist_ok=True)
    log = open(os.path.join(outdir, "ecfr_fetch_log.jsonl"), "a")
    for p in parts:
        url = API.format(date=date, part=p)
        for attempt in range(3):
            try:
                raw = fetch(url)
                break
            except Exception as e:  # noqa: BLE001
                err = repr(e)
                time.sleep(3)
        else:
            log.write(json.dumps({"part": p, "date": date, "url": url, "error": err}) + "\n")
            print("FAIL", p, err)
            continue
        root = ET.fromstring(raw)
        txt = render(root)
        open(os.path.join(d, f"part-{p}.txt"), "w").write(txt)
        rec = {"part": p, "date": date, "url": url, "retrieved_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
               "xml_sha256": hashlib.sha256(raw).hexdigest(), "txt_sha256": hashlib.sha256(txt.encode()).hexdigest(),
               "sections": txt.count("\n=== § ")}
        log.write(json.dumps(rec) + "\n")
        log.flush()
        print("ok", p, rec["sections"], len(txt))


if __name__ == "__main__":
    main()
