"""Check every data file against its schema and against each other.

Errors fail the run (exit code 1). Warnings are printed but don't fail.

Run:  python3 scripts/validate.py
Needs: pip install jsonschema
"""
import json
import re
import shutil
import subprocess
import sys
from collections import Counter

try:
    from jsonschema import Draft202012Validator
except ImportError:
    sys.exit("Missing package. Run: pip install jsonschema")

from common import APPS, NEEDS, PUBLISHER_DATA, REGISTRY, SCHEMA, read_json


def js_bad_patterns(patterns):
    """Patterns that do not compile as JavaScript regexes. Empty if node is not installed."""
    patterns = list(dict.fromkeys(patterns))
    if not patterns or not shutil.which("node"):
        return []
    js = ("const ps=JSON.parse(require('fs').readFileSync(0,'utf8'));"
          "const bad=ps.filter(p=>{try{new RegExp(p,'i');return false}catch(e){return true}});"
          "process.stdout.write(JSON.stringify(bad));")
    r = subprocess.run(["node", "-e", js], input=json.dumps(patterns), capture_output=True, text=True)
    return json.loads(r.stdout) if r.returncode == 0 and r.stdout else []

errors, warnings = [], []


def err(msg):
    errors.append(msg)


def warn(msg):
    warnings.append(msg)


def check_schema(validator, obj, where):
    for e in sorted(validator.iter_errors(obj), key=lambda e: list(e.path)):
        path = "/".join(str(p) for p in e.path) or "(root)"
        err(f"{where}: {path}: {e.message}")


def main():
    app_v = Draft202012Validator(read_json(SCHEMA / "app.schema.json"))
    pub_v = Draft202012Validator(read_json(SCHEMA / "publisher.schema.json"))
    need_v = Draft202012Validator(read_json(SCHEMA / "need.schema.json"))
    countries = set(read_json(SCHEMA / "iso-countries.json")["codes"])
    languages = set(read_json(SCHEMA / "iso-languages.json")["codes"])

    if not REGISTRY.exists():
        sys.exit("No data/registry.json. The registry is created once and kept in git; restore it from history.")
    registry = read_json(REGISTRY)
    reg_apps = registry["apps"]

    # Needs
    need_ids, orders, all_patterns = set(), Counter(), []
    for f in sorted(NEEDS.glob("*.json")):
        n = read_json(f)
        where = f"data/needs/{f.name}"
        check_schema(need_v, n, where)
        if f.stem != n.get("id"):
            err(f"{where}: file name does not match id {n.get('id')}")
        need_ids.add(n.get("id"))
        orders[n.get("order")] += 1
        for q in n.get("questions", []):
            for o in q.get("options", []):
                for p in o.get("patterns", []):
                    all_patterns.append(p)
                    try:
                        re.compile(p, re.I)
                    except re.error as e:
                        err(f"{where}: question {q.get('id')}: pattern {p!r} does not compile: {e}")
    bad_js = js_bad_patterns(all_patterns)
    for p in bad_js:
        err(f"data/needs: pattern {p!r} does not compile as a JavaScript regex (the site uses JavaScript)")
    for o, c in orders.items():
        if c > 1:
            err(f"data/needs: order {o} used by {c} needs")

    # Apps
    seen = {}
    for f in sorted(APPS.glob("*.json")):
        a = read_json(f)
        where = f"data/apps/{f.name}"
        check_schema(app_v, a, where)
        aid = a.get("appId")
        if aid in seen:
            err(f"{where}: appId also in {seen[aid]}")
        seen[aid] = f.name
        entry = reg_apps.get(aid)
        if not entry:
            err(f"{where}: appId not in registry")
        elif entry["stem"] != f.stem:
            err(f"{where}: registry says file should be {entry['stem']}.json")
        m = a.get("mapping", {})
        for p in m.get("primary", []):
            if p.get("need") not in need_ids:
                err(f"{where}: unknown need {p.get('need')}")
        for s in m.get("secondary", []):
            if s not in need_ids:
                err(f"{where}: unknown secondary need {s}")
        bad_c = [c for c in m.get("countries", []) if c not in countries]
        bad_l = [l for l in m.get("languages", []) if l.split("-")[0] not in languages]
        if bad_c or bad_l:
            warn(f"{where}: mapping has non-ISO codes {bad_c + bad_l}")
        if m.get("sourceHash") != a.get("source", {}).get("sourceHash") and not a.get("curated", {}).get("locked"):
            warn(f"{where}: mapping is stale (listing changed since it was mapped)")
    for aid, entry in reg_apps.items():
        if aid not in seen:
            err(f"registry: {aid} has no file data/apps/{entry['stem']}.json")

    # Publisher files
    pub_seen = set()
    for f in sorted(PUBLISHER_DATA.glob("*/*.json")):
        p = read_json(f)
        where = f"publisher-data/{f.parent.name}/{f.name}"
        check_schema(pub_v, p, where)
        aid = p.get("appId")
        entry = reg_apps.get(aid)
        if not entry:
            err(f"{where}: appId {aid} is not a known app")
            continue
        pub_seen.add(aid)
        if (entry["publisherFolder"], entry["stem"]) != (f.parent.name, f.stem):
            err(f"{where}: belongs at publisher-data/{entry['publisherFolder']}/{entry['stem']}.json")
        for c in p.get("countries", []):
            if c not in countries:
                err(f"{where}: {c} is not an ISO 3166-1 country code")
        for l in p.get("languages", []):
            if l.split("-")[0] not in languages:
                err(f"{where}: {l} is not an ISO 639-1 language code")
        ext, www = set(p.get("extends", [])), set(p.get("worksWellWith", []))
        for ref in ext | www:
            if ref not in reg_apps:
                err(f"{where}: {ref} is not a known app ID")
            if ref == aid:
                err(f"{where}: an app cannot reference itself")
        for ref in ext & www:
            err(f"{where}: {ref} is in both extends and worksWellWith; pick one")
        if p.get("showLogo") and not p.get("logoUrl"):
            err(f"{where}: showLogo is true but logoUrl is empty")
        if p.get("logoUrl") and not p.get("showLogo"):
            warn(f"{where}: logoUrl is set but showLogo is false, so no logo is shown")
    missing_pub = [aid for aid in reg_apps if aid not in pub_seen]
    if missing_pub:
        warn(f"publisher-data: {len(missing_pub)} apps have no publisher file")

    # Report
    for w in warnings[:20]:
        print("warn ", w)
    if len(warnings) > 20:
        print(f"warn  ... and {len(warnings) - 20} more warnings")
    for e in errors[:50]:
        print("ERROR", e)
    if len(errors) > 50:
        print(f"ERROR ... and {len(errors) - 50} more errors")
    print(f"\nChecked {len(seen)} apps, {len(need_ids)} needs, {len(pub_seen)} publisher files: "
          f"{len(errors)} errors, {len(warnings)} warnings")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
