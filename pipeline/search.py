"""Discogs search helper for the identification step.

Usage: python pipeline/search.py key=value [key=value ...]
  e.g. python pipeline/search.py barcode=045778043019
       python pipeline/search.py artist=Slint release_title=Spiderland format=Vinyl
       python pipeline/search.py q="kreukeltape lawine"
       python pipeline/search.py release=1158207      (full release: tracks, barcodes, labels)
Prints compact JSON results.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import search, spaced_barcodes  # noqa: E402
from enrich import fetch  # noqa: E402

ALLOWED = {"q", "barcode", "catno", "artist", "release_title", "label", "format", "type", "year", "track"}


def main():
    args = dict(a.split("=", 1) for a in sys.argv[1:] if "=" in a)
    if "release" in args:
        r = fetch("release", int(args["release"]))
        print(json.dumps({
            "id": r["id"], "artist": [a["name"] for a in r.get("artists", [])], "title": r.get("title"),
            "year": r.get("year"), "country": r.get("country"), "master_id": r.get("master_id"),
            "labels": [f"{l.get('name')} {l.get('catno')}" for l in r.get("labels", [])],
            "formats": [f.get("name") for f in r.get("formats", [])],
            "barcodes": [i["value"] for i in r.get("identifiers", []) if i.get("type") == "Barcode"],
            "tracks": [t.get("title") for t in r.get("tracklist", [])],
        }, ensure_ascii=False, indent=1))
        return
    params = {k: v for k, v in args.items() if k in ALLOWED}
    params.setdefault("type", "release")
    res = search(**params)
    if not res and params.get("barcode"):
        for s in spaced_barcodes(params["barcode"]):
            res = search(**{**params, "barcode": s})
            if res:
                break
    print(json.dumps([{"type": r.get("type"), "id": r.get("id"), "title": r.get("title"), "year": r.get("year"),
                       "label": (r.get("label") or [""])[0], "catno": r.get("catno"),
                       "format": r.get("format"), "barcode": (r.get("barcode") or [])[:2]} for r in res],
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
