"""Stage 2 prep: turn review decisions into import files.

Usage: python pipeline/export.py <batch> [--move-photos]
Reads work/<batch>/decisions.json (Claude saves this from the review artifact)
and work/<batch>/ident.json. Writes:
  export/<batch>_discogs_import.csv   release_id,Label,Title  (guroot/discogs-import format)
  collection.xlsx                     running master list; this batch's rows are replaced
With --move-photos, moves the batch's originals from unsorted/ to processed/<batch>/.
"""
import configparser
import csv
import json
import shutil
import sys
import time
import urllib.request
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
cfg = configparser.ConfigParser()
cfg.read(ROOT / "config.ini")
D = cfg["Discogs"]
COLS = ["Batch", "Record", "Artist", "Title", "Label", "Cat #", "Year", "Discogs Release ID",
        "Master ID", "Match", "Status", "Copy", "Discogs URL", "Photos", "Note", "Reviewed"]


def api(path):
    time.sleep(1.1)
    url = f"https://api.discogs.com{path}?key={D['consumer_key']}&secret={D['consumer_secret']}"
    req = urllib.request.Request(url, headers={"User-Agent": D.get("user_agent", "RecordPipeline/1.0")})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def resolve(dec):
    """Return (release_id, master_id, match_level, year, artist, title, label, catno)."""
    rid, mid, level = dec.get("release_id"), dec.get("master_id"), dec.get("level") or "pressing"
    info = {}
    if dec.get("type") == "master" and rid:
        m = api(f"/masters/{rid}")
        mid, rid, level = rid, m.get("main_release"), "album"
    if rid:
        try:
            info = api(f"/releases/{rid}")
            mid = mid or info.get("master_id")
        except Exception as e:
            print("  release lookup failed", rid, e)
    labels = info.get("labels") or [{}]
    return {
        "release_id": rid, "master_id": mid or None, "level": level,
        "year": info.get("year") or dec.get("year"),
        "artist": dec.get("artist") if dec.get("status") == "edited" and dec.get("artist") else
                  ", ".join(a["name"] for a in info.get("artists", [])) or dec.get("artist"),
        "title": dec.get("title") if dec.get("status") == "edited" and dec.get("title") else info.get("title") or dec.get("title"),
        "label": dec.get("label") if dec.get("status") == "edited" and dec.get("label") else labels[0].get("name") or dec.get("label"),
        "catno": dec.get("catno") if dec.get("status") == "edited" and dec.get("catno") else labels[0].get("catno") or dec.get("catno"),
        "url": f"https://www.discogs.com/release/{rid}" if rid else "",
    }


def main():
    batch = sys.argv[1]
    bdir = ROOT / "work" / batch
    decisions = json.loads((bdir / "decisions.json").read_text(encoding="utf-8"))
    idents = {r["id"]: r for r in json.loads((bdir / "ident.json").read_text(encoding="utf-8"))}
    rows, csv_rows, copies = [], [], {}
    for rid_rec in sorted(decisions):
        dec = decisions[rid_rec]
        if dec["status"] == "rejected":
            rows.append([batch, rid_rec, idents[rid_rec].get("artist"), idents[rid_rec].get("title"), "", "", "", "", "",
                         "", "rejected", "", "", " ".join(dec.get("photos", [])), dec.get("note", ""), dec.get("updated", "")])
            continue
        r = resolve(dec)
        copies[r["release_id"]] = copies.get(r["release_id"], 0) + 1
        rows.append([batch, rid_rec, r["artist"], r["title"], r["label"], r["catno"], r["year"], r["release_id"],
                     r["master_id"], r["level"], dec["status"], copies[r["release_id"]], r["url"],
                     " ".join(dec.get("photos", [])), dec.get("note", ""), dec.get("updated", "")])
        if r["release_id"]:
            csv_rows.append([r["release_id"], r["label"], f"{r['artist']} - {r['title']}"])
        print(rid_rec, dec["status"], r["release_id"], r["artist"], "-", r["title"])

    out = ROOT / "export"
    out.mkdir(exist_ok=True)
    with open(out / f"{batch}_discogs_import.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["release_id", "Label", "Title"])
        w.writerows(csv_rows)

    xl = ROOT / "collection.xlsx"
    if xl.exists():
        wb = load_workbook(xl)
        ws = wb.active
        keep = [list(r) for r in ws.iter_rows(min_row=2, values_only=True) if r[0] != batch]
        ws.delete_rows(2, ws.max_row)
        for r in keep:
            ws.append(r)
    else:
        wb = Workbook()
        ws = wb.active
        ws.title = "Collection"
        ws.append(COLS)
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = PatternFill("solid", fgColor="1F6F8B")
        ws.freeze_panes = "A2"
    for r in rows:
        ws.append(r)
    widths = [11, 8, 28, 36, 22, 16, 6, 14, 10, 9, 10, 6, 40, 16, 30, 22]
    for i, wdt in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = wdt
    ws.auto_filter.ref = ws.dimensions
    wb.save(xl)
    print(f"{len(csv_rows)} rows -> export/{batch}_discogs_import.csv; {len(rows)} rows -> collection.xlsx")

    if "--move-photos" in sys.argv:
        photos = json.loads((bdir / "photos.json").read_text())
        dest = ROOT / "processed" / batch
        dest.mkdir(parents=True, exist_ok=True)
        for p in photos:
            src = ROOT / "unsorted" / p["source"]
            if src.exists():
                shutil.move(str(src), dest / p["source"])
        print(f"moved originals to processed/{batch}/")


if __name__ == "__main__":
    main()
