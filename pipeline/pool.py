"""Stage 1c: build the pool of possible vinyl pressings for each record.

Usage: python pipeline/pool.py <batch>
Writes work/<batch>/pools.json: {record_id: {basis, master_id, pressings: [...]}}.
The review page asks guided questions that narrow each pool to one pressing.

How the pool is chosen (strongest evidence first):
  1. releases found by barcode       (all pressings sharing that barcode)
  2. album versions matching the catalog number read from the photo
  3. every vinyl version of the album (top 30 by how many people own it)
Each pressing in the pool gets its full Discogs details (cached in work/cache/).
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import ROOT, D, get  # noqa: E402
from enrich import fetch, summarize  # noqa: E402

MAX_POOL = 30
STD = {"lp", "album", "reissue", "repress", "remastered", "stereo", "mono", "limited edition", "numbered",
       "gatefold", "compilation", "ep", "single", "promo", "test pressing", "club edition", "deluxe edition",
       "special edition", "unofficial release", "misprint", "mispress", "33 ⅓ rpm", "45 rpm", "78 rpm",
       "12\"", "10\"", "7\"", "record store day", "picture disc", "white label", "maxi-single", "mini-album",
       "partially unofficial", "enhanced", "quadraphonic", "sampler", "transcription", "box set", "all media"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def versions(master_id):
    out, page = [], 1
    while page <= 5:
        url = (f"https://api.discogs.com/masters/{master_id}/versions?per_page=100&page={page}"
               f"&format=Vinyl&key={D['consumer_key']}&secret={D['consumer_secret']}")
        r = get(url)
        out += [v for v in r.get("versions", []) if "Vinyl" in (v.get("major_formats") or [])]
        if page >= r.get("pagination", {}).get("pages", 1):
            break
        page += 1
    return out


def pressing(rel):
    s = summarize(rel)
    discs, descs, colors = 0, [], []
    for f in rel.get("formats", []):
        if f.get("name") != "Vinyl":
            continue
        try:
            discs += int(f.get("qty") or 1)
        except ValueError:
            discs += 1
        for d in f.get("descriptions") or []:
            if d not in descs:
                descs.append(d)
        if f.get("text"):
            colors.append(f["text"].strip())
    labels = rel.get("labels") or [{}]
    mx = [i for i in rel.get("identifiers", []) if i.get("type") == "Matrix / Runout"]
    side_a = next((i for i in mx if re.search(r"\b(side )?a\b|a1|a-side", (i.get("description") or "").lower())), mx[0] if mx else None)
    return {
        "id": rel["id"], "artist": s["artist"], "title": s["title"],
        "year": rel.get("year") or None, "released": s["released"], "country": s["country"] or "Unknown",
        "label": labels[0].get("name", ""), "catno": labels[0].get("catno", ""),
        "discs": discs or 1, "descriptions": descs, "vinyl_text": "; ".join(colors),
        "matrix_a": side_a["value"].strip() if side_a else "", "matrix": s["matrix"],
        "barcodes": s["barcodes"], "notes": s["notes"], "have": s["have"] or 0,
        "url": f"https://www.discogs.com/release/{rel['id']}",
    }


def refresh(batch):
    """Recompute pressing fields from cached releases (no network)."""
    path = ROOT / "work" / batch / "pools.json"
    pools = json.loads(path.read_text(encoding="utf-8"))
    for pl in pools.values():
        pl["pressings"] = [pressing(fetch("release", p["id"])) for p in pl["pressings"]]
    path.write_text(json.dumps(pools, indent=1, ensure_ascii=False), encoding="utf-8")


def main():
    batch = sys.argv[1]
    if "--refresh" in sys.argv:
        return refresh(batch)
    bdir = ROOT / "work" / batch
    idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
    matches = json.loads((bdir / "matches.json").read_text(encoding="utf-8"))
    path = bdir / "pools.json"
    pools = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    for rec in idents:
        rid = rec["id"]
        if rid in pools:
            continue
        if rec.get("needs_reident"):
            continue  # waiting for Claude to re-read the photos
        cands = matches.get(rid, [])
        master = next((c["id"] for c in cands if c["type"] == "master"), None) or \
            next((c["master_id"] for c in cands if c.get("master_id")), None)
        bc = [c for c in cands if c["via"] == "barcode" and c["type"] == "release"]
        # Barcodes get reused; drop hits for a different album when the title is known.
        same = [c for c in bc if rec.get("title") and norm(rec["title"]) in norm(c.get("title"))]
        bc_ids = [c["id"] for c in (same or bc)]
        ids, basis = [], ""
        if bc_ids:
            ids, basis = bc_ids, f"The barcode {rec.get('barcode')} matches {len(bc_ids)} pressing{'s' if len(bc_ids) > 1 else ''} on Discogs."
        vers = versions(master) if master and not ids else []
        if not ids and rec.get("catno"):
            want = norm(rec["catno"])
            hit = [v for v in vers if want and (want in norm(v.get("catno")) or norm(v.get("catno")) in want and len(norm(v.get("catno"))) > 3)]
            if hit:
                hit.sort(key=lambda v: -((v.get("stats") or {}).get("community") or {}).get("in_collection", 0))
                ids = [v["id"] for v in hit]
                basis = f"The catalog number {rec['catno']} matches {len(hit)} vinyl pressing{'s' if len(hit) > 1 else ''}" + \
                        (f"; showing the {MAX_POOL} most common." if len(hit) > MAX_POOL else ".")
            else:
                cat_ids = [c["id"] for c in cands if c["via"] == "catno" and c["type"] == "release"]
                if cat_ids:
                    ids, basis = cat_ids, f"The catalog number {rec['catno']} matches {len(cat_ids)} release{'s' if len(cat_ids) > 1 else ''}."
        if not ids and vers:
            vers.sort(key=lambda v: -((v.get("stats") or {}).get("community") or {}).get("in_collection", 0))
            ids = [v["id"] for v in vers[:MAX_POOL]]
            basis = f"Discogs lists {len(vers)} vinyl pressing{'s' if len(vers) > 1 else ''} of this album" + \
                    (f"; showing the {MAX_POOL} most common." if len(vers) > MAX_POOL else ".")
        if not ids:
            ids = [c["id"] for c in cands if c["type"] == "release"]
            basis = "No album grouping on Discogs; these are the search results."
        excluded = set(rec.get("exclude") or [])
        ids = [i for i in ids if i not in excluded]
        press = []
        for i in ids[:MAX_POOL]:
            try:
                rel = fetch("release", i)
                if any(f.get("name") == "Vinyl" for f in rel.get("formats", [])):
                    press.append(pressing(rel))
            except Exception as e:
                print("  failed", i, e)
        pools[rid] = {"basis": basis, "master_id": master, "pressings": press}
        print(rid, len(press), basis)
        path.write_text(json.dumps(pools, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
