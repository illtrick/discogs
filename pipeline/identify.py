"""Stage 1a: identify records from photos, using Claude Code headless (`claude -p`).

Usage: python pipeline/identify.py <batch>            identify every photo -> ident.json
       python pipeline/identify.py <batch> --reident  re-read only records flagged needs_reident
Claude reads the photos itself and may use pipeline/search.py to check Discogs. It returns
the records as JSON in its reply and this script writes ident.json: Claude Code won't write
inside ~/.claude/ (where this project lives) even with edits auto-accepted.
"""
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """Each record is one JSON object:
  {"id": "r01", "photos": ["p001", "p002"], "artist": "", "title": "", "label": "", "catno": "",
   "barcode": "", "confidence": "high|medium|low", "notes": ""}
- Use "" for anything you cannot read; never invent. Barcode: digits only.
- catno = catalog number exactly as printed. Notes: short; mention what you could and couldn't read.
- Artist "Various" for compilations."""

NEW = """You are identifying vinyl records from phone photos for a Discogs intake pipeline.
Working directory: {root}

Batch: {batch}. The photo list is in work/{batch}/photos.json (id, file, source = original
filename with capture time). Photos are JPGs at work/{batch}/<file>.

1. Read EVERY photo with the Read tool.
2. Group photos into records. Photos taken within a short time of each other that show the same
   record (cover, back, label, barcode, spine) are ONE record. The owner sometimes photographs only
   the barcode or catalog number. Two separate photo groups of the same album are two copies only
   if they are clearly two physical records; say so in notes ("Copy 1 of 2").
   Photos too blurry to use belong to no record.
3. Check doubtful ones on Discogs with: python pipeline/search.py key=value ...
   (keys: q, barcode, catno, artist, release_title, label, format, track; or release=<id> for
   full details incl. track list). Use it to confirm artist/title, not to guess the pressing.
4. Do NOT write any files. Records are numbered r01, r02, ... in photo order.

{schema}

Your final reply must be ONLY the JSON array of records, in a ```json code block, nothing else."""

REIDENT = """You are re-identifying vinyl records whose earlier identification the owner REJECTED.
Working directory: {root}

These records need re-identifying (current, rejected data):
{records}
For each one:
1. Read its photos (work/{batch}/photos/<photo id>.jpg) with the Read tool and look again,
   carefully: small print, track names, credits, barcode digits, catalog numbers, label logos.
2. The earlier guess (artist/title in the record) was WRONG. Discogs ids in its "exclude" list
   were rejected. Find a different answer.
3. Check on Discogs with: python pipeline/search.py key=value ...
   (keys: q, barcode, catno, artist, release_title, label, format, track; or release=<id>).
   Barcodes may be stored with spaces; track-title searches (q="track names") often work.
4. Do NOT write any files. Update artist, title, label, catno, barcode, confidence and notes
   (say what new evidence you used). Keep the same id and photos. If you truly cannot identify
   it, leave artist/title "", set confidence "low" and explain in notes.

{schema}

Your final reply must be ONLY a JSON array of the updated records, in a ```json code block."""


def claude_bin():
    exe = shutil.which("claude") or str(Path.home() / ".local" / "bin" / "claude.exe")
    return exe


def run_claude(prompt):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_", "ANTHROPIC_"))}
    cmd = [claude_bin(), "-p", prompt, "--output-format", "json",
           "--permission-mode", "acceptEdits",
           "--allowedTools", "Read", "Glob", "Bash(python pipeline/search.py:*)"]
    r = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8",
                       timeout=60 * 60)
    if r.returncode != 0:
        raise SystemExit(f"claude failed ({r.returncode}): {r.stderr[-2000:] or r.stdout[-2000:]}")
    try:
        out = json.loads(r.stdout)
    except json.JSONDecodeError:
        raise SystemExit("unexpected output from claude: " + r.stdout[-2000:])
    text = (out.get("result") or "").strip()
    if out.get("is_error"):
        raise SystemExit("claude reported an error: " + text[-2000:])
    return parse_records(text)


def parse_records(text):
    """The JSON array from Claude's reply (fenced or bare)."""
    m = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.S)
    raw = m.group(1) if m else text[text.find("["): text.rfind("]") + 1]
    try:
        recs = json.loads(raw)
    except ValueError:
        raise SystemExit("couldn't read records from claude's reply: " + text[-3000:])
    if not isinstance(recs, list) or not all(isinstance(r, dict) and r.get("id") for r in recs):
        raise SystemExit("claude's reply wasn't a list of records: " + text[-3000:])
    return recs


def clean(r):
    r.setdefault("photos", [])
    for k in ("artist", "title", "label", "catno", "barcode", "notes"):
        r[k] = str(r.get(k) or "")
    r["barcode"] = "".join(c for c in r["barcode"] if c.isdigit())
    if r.get("confidence") not in ("high", "medium", "low"):
        r["confidence"] = "low"
    return r


def main():
    batch = sys.argv[1]
    bdir = ROOT / "work" / batch
    path = bdir / "ident.json"
    if "--reident" in sys.argv:
        idents = json.loads(path.read_text(encoding="utf-8"))
        todo = [r for r in idents if r.get("needs_reident")]
        if not todo:
            print("nothing to re-identify")
            return
        shown = [{k: r.get(k) for k in ("id", "photos", "artist", "title", "label", "catno", "barcode", "notes", "exclude")}
                 for r in todo]
        new = {r["id"]: r for r in run_claude(REIDENT.format(
            root=ROOT, batch=batch, records=json.dumps(shown, indent=1, ensure_ascii=False), schema=SCHEMA))}
        for r in idents:
            if r["id"] in new:
                upd = new[r["id"]]
                for k in ("artist", "title", "label", "catno", "barcode", "confidence", "notes"):
                    if k in upd:
                        r[k] = upd[k]
                r.pop("needs_reident", None)
                clean(r)
                print(r["id"], r["artist"], "-", r["title"])
    else:
        idents = [clean(r) for r in run_claude(NEW.format(root=ROOT, batch=batch, schema=SCHEMA))]
        for r in idents:
            print(r["id"], r["artist"] or "?", "-", r["title"] or "?", f"({r['confidence']})")
    path.write_text(json.dumps(idents, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(idents)} records in ident.json; {sum(1 for r in idents if r.get('needs_reident'))} still flagged")

if __name__ == "__main__":
    main()
