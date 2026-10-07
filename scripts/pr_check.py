"""Check a pull request that changes publisher files, and write a PR comment.

Runs in GitHub Actions on pull_request_target. It reads the PR's files as data
only and never runs anything from the PR. Rules and reference data (schema,
registry, ISO codes, this script) come from the trusted base branch.

Usage:
  python scripts/pr_check.py --base <base checkout> --pr <pr checkout>
                             --files <changed files tsv> --out <comment.md>
Exit code 1 when the PR needs changes.
"""
import argparse
import json
import struct
import urllib.request
from pathlib import Path

from jsonschema import Draft202012Validator

MARKER = "<!-- findmybc-pr-check -->"
MAX_LOGO = 2 * 1024 * 1024
FIELDS = ["countries", "languages", "extends", "worksWellWith", "showLogo", "logoUrl"]


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sniff(data):
    """Image type and size in pixels (when easy to read) from the first bytes."""
    head = data[:2048]
    if head.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return "PNG", (w, h)
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG", None
    if head[:6] in (b"GIF87a", b"GIF89a"):
        w, h = struct.unpack("<HH", data[6:10])
        return "GIF", (w, h)
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return "WebP", None
    if head[:4] == b"\x00\x00\x01\x00":
        return "ICO", None
    text = head.decode("utf-8", "ignore").lstrip().lower()
    if text.startswith("<svg") or (text.startswith("<?xml") and "<svg" in text):
        return "SVG", None
    return None, None


def check_logo(url):
    """Fetch the logo. Returns (problem or None, facts line)."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "findmybc.app PR check"})
        with urllib.request.urlopen(req, timeout=15) as r:
            final = r.geturl()
            ctype = r.headers.get("Content-Type", "?").split(";")[0]
            data = r.read(MAX_LOGO + 1)
    except Exception as e:
        return f"the logo URL could not be fetched ({e.__class__.__name__}: {e})", ""
    if not final.startswith("https://"):
        return f"the logo URL redirects to a non-https address: {final}", ""
    if len(data) > MAX_LOGO:
        return "the logo is larger than 2 MB", ""
    kind, dims = sniff(data)
    facts = f"{kind or 'unknown'}, {len(data) / 1024:.0f} KB" + (f", {dims[0]}×{dims[1]} px" if dims else "") + f", served as `{ctype}`"
    if not kind:
        return f"the logo URL does not return an image (served as `{ctype}`)", facts
    if dims and (dims[0] < 32 or dims[1] < 32):
        return f"the logo is very small ({dims[0]}×{dims[1]} px)", facts
    if final != url:
        facts += f", redirects to {final}"
    return None, facts


def show(v):
    if v in (None, [], ""):
        return "(empty)"
    return "`" + json.dumps(v, ensure_ascii=False) + "`"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True)
    ap.add_argument("--pr", required=True)
    ap.add_argument("--files", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    base, pr = Path(a.base), Path(a.pr)

    schema = Draft202012Validator(read(base / "schema/publisher.schema.json"))
    reg = read(base / "data/registry.json")["apps"]
    countries = set(read(base / "schema/iso-countries.json")["codes"])
    languages = set(read(base / "schema/iso-languages.json")["codes"])

    errors, notes, sections = [], [], []
    rows = [l.split("\t", 1) for l in Path(a.files).read_text().splitlines() if l.strip()]
    for status, name in rows:
        if not (name.startswith("publisher-data/") and name.endswith(".json") and name.count("/") == 2):
            errors.append(f"`{name}`: only files at `publisher-data/<publisher>/<app>.json` may change in a publisher pull request")
            continue
        folder, stem = name.split("/")[1], name.split("/")[2][:-5]
        if status == "removed":
            notes.append(f"`{name}` is removed. The app stays on the site as long as it is in the Marketplace catalog, just without these supplements. Ask why if unsure.")
            continue
        try:
            p = read(pr / name)
        except Exception as e:
            errors.append(f"`{name}`: not valid JSON ({e})")
            continue
        where = f"`{name}`"
        for e in schema.iter_errors(p):
            errors.append(f"{where}: {e.message}")
        aid = p.get("appId")
        entry = reg.get(aid)
        if not entry:
            errors.append(f"{where}: appId `{aid}` is not a known app")
            continue
        if (entry["publisherFolder"], entry["stem"]) != (folder, stem):
            errors.append(f"{where}: this app belongs at `publisher-data/{entry['publisherFolder']}/{entry['stem']}.json`")
        old = None
        if (base / name).exists():
            old = read(base / name)
            for k in ("appId", "appName"):
                if old.get(k) != p.get(k):
                    errors.append(f"{where}: `{k}` must not be changed")
        for c in p.get("countries") or []:
            if c not in countries:
                errors.append(f"{where}: `{c}` is not an ISO 3166-1 country code")
        for l in p.get("languages") or []:
            if l.split("-")[0] not in languages:
                errors.append(f"{where}: `{l}` is not an ISO 639-1 language code")
        for ref in set(p.get("extends") or []) | set(p.get("worksWellWith") or []):
            if ref not in reg:
                errors.append(f"{where}: `{ref}` is not a known app ID")
            elif ref == aid:
                errors.append(f"{where}: an app cannot reference itself")

        app = read(base / f"data/apps/{entry['stem']}.json")["source"]
        lines = [f"### {app['name']}", f"{app['publisher']} · [Marketplace listing]({app['url']})", ""]
        changed = [k for k in FIELDS if (old or {}).get(k) != p.get(k)]
        if changed:
            lines += ["| Field | Before | After |", "| --- | --- | --- |"]
            lines += [f"| {k} | {show((old or {}).get(k))} | {show(p.get(k))} |" for k in changed]
        else:
            lines.append("No field changes.")
        url = p.get("logoUrl")
        if p.get("showLogo") and not url:
            errors.append(f"{where}: `showLogo` is true but `logoUrl` is empty")
        if url and ("logoUrl" in changed or "showLogo" in changed):
            problem, facts = check_logo(url)
            if problem:
                errors.append(f"{where}: {problem}")
            lines += ["", "**Logo**" + (f" ({facts})" if facts else ""), "",
                      f'<img src="{url}" height="96" alt="logo"> &nbsp; <img src="{url}" height="40" alt="logo small">']
        sections.append("\n".join(lines))

    ok = not errors
    out = [MARKER,
           "## " + ("✅ Publisher file check passed" if ok else "❌ Publisher file needs changes"), ""]
    if errors:
        out += ["**Problems**", ""] + [f"- {e}" for e in errors] + [""]
    if notes:
        out += ["**Worth a look**", ""] + [f"- {n}" for n in notes] + [""]
    out += ["\n\n".join(sections)]
    out += ["", "---", "_Before merging: confirm the author works for this publisher._"]
    Path(a.out).write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
