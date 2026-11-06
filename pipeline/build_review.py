"""Stage 1c: assemble the review artifact's files for a batch.

Usage: python pipeline/build_review.py <batch>
Writes review/ (the folder that gets published):
  review/batch.json        records + Discogs candidates
  review/photos/<batch>/   your photos, resized
  review/covers/           Discogs cover images
review/index.html is the page itself and is not touched here.
"""
import json
import shutil
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "review"


def main():
    batch = sys.argv[1]
    bdir = ROOT / "work" / batch
    photos = json.loads((bdir / "photos.json").read_text())
    idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
    matches = json.loads((bdir / "matches.json").read_text(encoding="utf-8"))
    pp = bdir / "pools.json"
    pools = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else {}

    pdir = SITE / "photos" / batch
    cdir = SITE / "covers"
    # Only the current batch's photos and covers are published.
    if (SITE / "photos").exists():
        for old in (SITE / "photos").iterdir():
            if old.name != batch:
                shutil.rmtree(old)
    shutil.rmtree(cdir, ignore_errors=True)
    pdir.mkdir(parents=True, exist_ok=True)
    cdir.mkdir(parents=True, exist_ok=True)

    for p in photos:
        dst = pdir / f"{p['id']}.jpg"
        if not dst.exists():
            im = Image.open(bdir / p["file"])
            im.thumbnail((900, 900))
            im.save(dst, quality=78)

    used = set()
    records = []
    for rec in idents:
        used.update(rec["photos"])
        cands = matches.get(rec["id"], [])
        for c in cands:
            if c.get("cover"):
                src = bdir / c["cover"]
                if src.exists():
                    shutil.copy2(src, cdir / src.name)
                    c["cover"] = f"covers/{src.name}"
                else:
                    c["cover"] = None
        records.append({**rec, "candidates": cands, "pool": pools.get(rec["id"], {"basis": "", "pressings": []})})

    data = {
        "batch": batch,
        "photoBase": f"photos/{batch}/",
        "covers": sorted(f.stem for f in cdir.glob("r*.jpg")),
        "records": records,
        "unused": [p["id"] for p in photos if p["id"] not in used],
    }
    (SITE / "batch.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    # The runner serves each batch to the artifact from here (photos/covers from work/<batch>/).
    data["covers"] = sorted(f.stem for f in (bdir / "covers").glob("r*.jpg"))
    (bdir / "batch.json").write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    files = sorted(str(f.relative_to(SITE)).replace("\\", "/") for f in SITE.rglob("*")
                   if f.is_file() and f.name != "index.html")
    (bdir / "publish_files.json").write_text(json.dumps(files, indent=1))
    print(f"{len(records)} records, {len(data['unused'])} unused photos, {len(files)} files to publish")


if __name__ == "__main__":
    main()
