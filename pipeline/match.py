"""Stage 1b: search Discogs for each identified record.

Usage: python pipeline/match.py <batch>
Reads work/<batch>/ident.json, writes work/<batch>/matches.json and downloads
cover images into work/<batch>/covers/.

Search order per record (stops adding once it has enough candidates):
  1. barcode            -> exact pressing
  2. catalog number (+ artist when known) -> pressing
  3. artist + title, vinyl releases       -> pressing guess
  4. artist + title masters               -> album-level fallback
Then run pipeline/enrich.py to add full pressing details to each candidate.
"""
import configparser
import io
import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
cfg = configparser.ConfigParser()
cfg.read(ROOT / "config.ini")
D = cfg["Discogs"]
UA = D.get("user_agent", "RecordPipeline/1.0")
MAX_CANDIDATES = 5
_last = [0.0]


def get(url, raw=False):
    # Authenticated Discogs limit is 60 req/min; stay under it.
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                data = r.read()
            return data if raw else json.loads(data)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            raise
    raise RuntimeError(f"rate limited: {url}")


def search(**params):
    params = {k: v for k, v in params.items() if v}
    params.update(key=D["consumer_key"], secret=D["consumer_secret"], per_page=10)
    url = "https://api.discogs.com/database/search?" + urllib.parse.urlencode(params)
    return get(url).get("results", [])


def norm(s):
    return "".join(c for c in (s or "").lower() if c.isalnum())


def candidate(r, via, level):
    return {
        "type": r.get("type"),
        "id": r.get("id"),
        "master_id": r.get("master_id"),
        "title": r.get("title"),
        "year": r.get("year"),
        "country": r.get("country"),
        "label": (r.get("label") or [""])[0],
        "catno": r.get("catno"),
        "format": ", ".join(r.get("format") or []),
        "barcode": (r.get("barcode") or [])[:2],
        "cover_url": r.get("cover_image"),
        "url": "https://www.discogs.com" + (r.get("uri") or ""),
        "via": via,
        "level": level,
    }


def spaced_barcodes(bc):
    d = "".join(c for c in bc if c.isdigit())
    if len(d) == 13:
        return [f"{d[0]} {d[1:7]} {d[7:]}", f"{d[0]} {d[1:6]} {d[6:11]} {d[11:]}"]
    if len(d) == 12:
        return [f"{d[0]} {d[1:6]} {d[6:11]} {d[11]}"]
    return []


def match(rec):
    cands, seen = [], set()
    excluded = set(rec.get("exclude") or [])  # ids you rejected in an earlier review round

    def add(results, via, level, filt=None):
        for r in results:
            key = (r.get("type"), r.get("id"))
            if key in seen or r.get("id") in excluded or (filt and not filt(r)):
                continue
            seen.add(key)
            cands.append(candidate(r, via, level))

    artist, title = rec.get("artist"), rec.get("title")
    a_ok = (lambda r: norm(artist.split("/")[0].split(",")[0])[:6] in norm(r.get("title"))) if artist and artist != "Various" else None
    if rec.get("barcode"):
        add(search(barcode=rec["barcode"], type="release"), "barcode", "pressing")
        if not cands:  # Discogs often stores barcodes with spaces, which exact search misses
            for spaced in spaced_barcodes(rec["barcode"]):
                add(search(barcode=spaced, type="release"), "barcode", "pressing")
                if cands:
                    break
    if rec.get("catno") and len(cands) < MAX_CANDIDATES:
        add(search(catno=rec["catno"], type="release"), "catno", "pressing", a_ok)
    if artist and title and len(cands) < MAX_CANDIDATES:
        q = dict(artist=None if artist == "Various" else artist, release_title=title)
        add(search(type="release", format="Vinyl", **q), "artist+title", "pressing")
        add(search(type="master", **q), "master", "album")
    if (title or artist) and not cands:
        add(search(q=f"{artist} {title}".strip(), type="release"), "text", "pressing")
    if title and not cands:
        add(search(q=title, type="release"), "title only", "pressing")
    return cands[: MAX_CANDIDATES + 2]


def save_cover(url, dst):
    if dst.exists() or not url or url.endswith("spacer.gif"):
        return dst.exists()
    try:
        im = Image.open(io.BytesIO(get(url, raw=True))).convert("RGB")
        im.thumbnail((500, 500))
        im.save(dst, quality=82)
        return True
    except Exception as e:  # cover art is nice-to-have
        print("  cover failed:", e)
        return False


def main():
    batch = sys.argv[1]
    bdir = ROOT / "work" / batch
    covers = bdir / "covers"
    covers.mkdir(exist_ok=True)
    idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
    out_path = bdir / "matches.json"
    done = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    for rec in idents:
        if rec["id"] in done:
            continue
        if rec.get("needs_reident"):
            continue  # waiting for Claude to re-read the photos
        cands = match(rec)
        for c in cands:
            name = f"{c['type'][0]}{c['id']}.jpg"
            c["cover"] = f"covers/{name}" if save_cover(c.pop("cover_url"), covers / name) else None
        done[rec["id"]] = cands
        print(rec["id"], rec.get("artist") or "?", "-", rec.get("title") or "?", "->", len(cands),
              cands[0]["title"] if cands else "NO MATCH")
        out_path.write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
