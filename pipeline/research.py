"""Stage 1d: automatically re-search records you edited or rejected in review.

Usage: python pipeline/research.py <batch>
Reads work/<batch>/decisions.json (saved from the review artifact) and, for each
record whose latest decision is "edited" (without a Discogs link) or "rejected":
  edited   -> your artist / title / label / catalog # replace my guess
  rejected -> every Discogs id I showed you before is excluded, and the record
              is flagged needs_reident so Claude re-reads the photos
Then it clears that record's old candidates and pool, bumps its review round
(so the review page shows it as "To review" again) and re-runs
match -> enrich -> pool for just those records.

Records flagged needs_reident are listed at the end; once Claude has updated
their artist/title in ident.json (and removed the flag), run this again.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(p, default):
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default


def main():
    batch = sys.argv[1]
    bdir = ROOT / "work" / batch
    idents = load(bdir / "ident.json", [])
    decisions = load(bdir / "decisions.json", {})
    matches = load(bdir / "matches.json", {})
    pools = load(bdir / "pools.json", {})

    changed = []
    for rec in idents:
        d = decisions.get(rec["id"])
        rnd = rec.get("round", 0)
        if not d or d.get("round", 0) < rnd:
            continue  # no decision yet for the current round
        if d["status"] == "edited" and not d.get("release_id"):
            for k in ("artist", "title", "label", "catno"):
                if d.get(k):
                    rec[k] = d[k]
            rec["notes"] = (f"Re-searched with your edit (round {rnd + 1}). " + (d.get("note") or "")).strip()
        elif d["status"] == "rejected":
            old = {c["id"] for c in matches.get(rec["id"], [])}
            old |= {p["id"] for p in pools.get(rec["id"], {}).get("pressings", [])}
            if pools.get(rec["id"], {}).get("master_id"):
                old.add(pools[rec["id"]]["master_id"])
            rec["exclude"] = sorted(set(rec.get("exclude") or []) | old)
            rec["needs_reident"] = True
            rec["notes"] = f"You rejected round {rnd}'s match; re-identifying. " + (d.get("note") or "")
        else:
            continue
        rec["round"] = rnd + 1
        rec["confidence"] = "medium"
        matches.pop(rec["id"], None)
        pools.pop(rec["id"], None)
        changed.append(rec["id"])

    (bdir / "ident.json").write_text(json.dumps(idents, indent=1, ensure_ascii=False), encoding="utf-8")
    (bdir / "matches.json").write_text(json.dumps(matches, indent=1, ensure_ascii=False), encoding="utf-8")
    (bdir / "pools.json").write_text(json.dumps(pools, indent=1, ensure_ascii=False), encoding="utf-8")
    print("re-searching:", ", ".join(changed) or "nothing new")

    for step in ("match", "enrich", "pool"):
        subprocess.run([sys.executable, str(ROOT / "pipeline" / f"{step}.py"), batch], check=True)

    waiting = [r["id"] for r in idents if r.get("needs_reident")]
    if waiting:
        print("needs re-identification from photos:", ", ".join(waiting))


if __name__ == "__main__":
    main()
