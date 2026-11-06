"""Stage 1b+: add full Discogs release details to every candidate.

Usage: python pipeline/enrich.py <batch>
Adds a `details` object to each candidate in work/<batch>/matches.json:
vinyl color/format text, release date, notes, matrix/runout etchings,
barcodes, labels, community have/want. Responses are cached in work/cache/.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import ROOT, D, get  # noqa: E402

CACHE = ROOT / "work" / "cache"
CACHE.mkdir(parents=True, exist_ok=True)


def fetch(kind, i):
    f = CACHE / f"{kind}-{i}.json"
    if f.exists():
        return json.loads(f.read_text(encoding="utf-8"))
    data = get(f"https://api.discogs.com/{kind}s/{i}?key={D['consumer_key']}&secret={D['consumer_secret']}")
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def summarize(rel):
    fmts = []
    for f in rel.get("formats", []):
        parts = [f"{f.get('qty', '1')}× {f.get('name', '')}" if f.get("qty") not in (None, "1") else f.get("name", "")]
        parts += f.get("descriptions", []) or []
        if f.get("text"):
            parts.append(f["text"])
        fmts.append(", ".join(p for p in parts if p))
    ids = rel.get("identifiers", [])
    matrix = [f"{i.get('description') + ': ' if i.get('description') else ''}{i['value']}"
              for i in ids if i.get("type") == "Matrix / Runout"]
    barcodes = sorted({i["value"] for i in ids if i.get("type") == "Barcode"})
    other = [f"{i['type']}: {i['value']}" for i in ids
             if i.get("type") not in ("Matrix / Runout", "Barcode", "Rights Society")][:4]
    comm = rel.get("community", {})
    artist = ""
    for a in rel.get("artists", []):
        name = re.sub(r"\s*\(\d+\)$", "", a.get("name", "")).rstrip("*")
        join = (a.get("join") or "").strip()
        artist += name + (", " if join == "," else f" {join} " if join else "")
    artist = artist.strip()
    return {
        "artist": artist,
        "title": rel.get("title", ""),
        "released": rel.get("released_formatted") or rel.get("released") or (str(rel["year"]) if rel.get("year") else ""),
        "country": rel.get("country", ""),
        "formats": fmts,
        "labels": [f"{l.get('name')} – {l.get('catno')}" for l in rel.get("labels", [])],
        "matrix": matrix[:6],
        "barcodes": barcodes[:3],
        "other_ids": other,
        "notes": (rel.get("notes") or "").strip()[:700],
        "have": comm.get("have"),
        "want": comm.get("want"),
        "tracks": len([t for t in rel.get("tracklist", []) if t.get("type_") == "track"]),
    }


def main():
    batch = sys.argv[1]
    path = ROOT / "work" / batch / "matches.json"
    matches = json.loads(path.read_text(encoding="utf-8"))
    for rid, cands in matches.items():
        for c in cands:
            if c.get("details") and "title" in c["details"]:
                continue
            try:
                if c["type"] == "master":
                    m = fetch("master", c["id"])
                    main_rel = fetch("release", m["main_release"]) if m.get("main_release") else {}
                    det = summarize(main_rel)
                    det["note_level"] = f"Album-level match. Details shown are from the main release ({m.get('main_release')}); Discogs lists {m.get('num_versions') or 'several'} versions."
                    c["details"] = det
                else:
                    c["details"] = summarize(fetch("release", c["id"]))
            except Exception as e:
                print("  failed", c["type"], c["id"], e)
        print(rid, "ok")
        path.write_text(json.dumps(matches, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
