"""Stage 2: add an exported batch to your Discogs collection.

Usage: python pipeline/add_to_discogs.py <batch> [--dry-run]
Reads export/<batch>_discogs_import.csv and adds each release to the folder set
by `collection_folder` in config.ini (1 = Uncategorized), using `token` and
`username`. Safe to re-run: it first counts the copies of each release already
in your collection and only adds the missing ones (so two rows for the same
release, like the KRS-One duplicate, end up as two copies).
Writes work/<batch>/added.json with the instance id of each copy added.
"""
import collections
import csv
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from match import ROOT, D, UA, _last  # noqa: E402
import time  # noqa: E402

USER = D["username"]
FOLDER = D.get("collection_folder", "1") or "1"


def api(path, method="GET"):
    wait = 1.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    _last[0] = time.time()
    req = urllib.request.Request("https://api.discogs.com" + path, method=method,
                                 headers={"User-Agent": UA, "Authorization": "Discogs token=" + D["token"],
                                          "Content-Length": "0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                body = r.read()
            return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(10 * (attempt + 1))
                continue
            raise
    raise RuntimeError("rate limited: " + path)


def owned():
    have, page = collections.Counter(), 1
    while True:
        r = api(f"/users/{USER}/collection/folders/0/releases?per_page=100&page={page}")
        for rel in r.get("releases", []):
            have[rel["id"]] += 1
        if page >= r.get("pagination", {}).get("pages", 1):
            return have
        page += 1


def main():
    batch = sys.argv[1]
    dry = "--dry-run" in sys.argv
    rows = list(csv.DictReader(open(ROOT / "export" / f"{batch}_discogs_import.csv", encoding="utf-8")))
    want = collections.Counter(int(r["release_id"]) for r in rows)
    names = {int(r["release_id"]): r["Title"] for r in rows}
    have = owned()
    print(f"{sum(have.values())} items already in your collection")
    log_path = ROOT / "work" / batch / "added.json"
    log = json.loads(log_path.read_text(encoding="utf-8")) if log_path.exists() else []
    added = skipped = 0
    for rid, n in want.items():
        missing = n - have[rid]
        if missing <= 0:
            skipped += 1
            print("  already have", rid, names[rid])
            continue
        for _ in range(missing):
            if dry:
                print("  would add", rid, names[rid])
                continue
            r = api(f"/users/{USER}/collection/folders/{FOLDER}/releases/{rid}", method="POST")
            log.append({"release_id": rid, "instance_id": r.get("instance_id"), "title": names[rid]})
            log_path.write_text(json.dumps(log, indent=1, ensure_ascii=False), encoding="utf-8")
            added += 1
            print("  added", rid, names[rid])
    print(f"{'would add' if dry else 'added'} {added if not dry else sum(max(0, n - have[r]) for r, n in want.items())}, "
          f"{skipped} already in collection")


if __name__ == "__main__":
    main()
