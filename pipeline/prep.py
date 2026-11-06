"""Stage 0: convert photos in unsorted/ to JPGs in work/<batch>/photos/.

Usage: python pipeline/prep.py [batch_name]
batch_name defaults to today's date. Writes work/<batch>/photos.json listing
each photo with its capture timestamp (from the filename or EXIF).
"""
import json
import sys
from datetime import date
from pathlib import Path

from PIL import Image, ImageOps
import pillow_heif

pillow_heif.register_heif_opener()

ROOT = Path(__file__).resolve().parent.parent
UNSORTED = ROOT / "unsorted"
EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
MAX_EDGE = 1400


def main():
    batch = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    out = ROOT / "work" / batch / "photos"
    out.mkdir(parents=True, exist_ok=True)
    photos = []
    for i, src in enumerate(sorted(p for p in UNSORTED.iterdir() if p.suffix.lower() in EXTS), 1):
        pid = f"p{i:03d}"
        dst = out / f"{pid}.jpg"
        if not dst.exists():
            im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
            im.thumbnail((MAX_EDGE, MAX_EDGE))
            im.save(dst, quality=85)
        photos.append({"id": pid, "file": f"photos/{pid}.jpg", "source": src.name})
        print(pid, src.name)
    (out.parent / "photos.json").write_text(json.dumps(photos, indent=2))
    print(f"{len(photos)} photos -> {out}")


if __name__ == "__main__":
    main()
