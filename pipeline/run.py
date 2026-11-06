"""Pipeline runner: what the review artifact's buttons trigger (via pipeline/mcp_server.py).

Usage: python pipeline/run.py intake            new photos in unsorted/ -> a new batch ready to review
       python pipeline/run.py finish <batch>    after review: re-search edited/rejected records, or,
                                                when everything is confirmed, export + add to Discogs
Progress is written to work/_runner/status.json; output to work/_runner/<job>.log.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import traceback
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNNER = ROOT / "work" / "_runner"
RUNNER.mkdir(parents=True, exist_ok=True)
STATUS = RUNNER / "status.json"
EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}


class Job:
    def __init__(self, kind, batch, steps):
        self.s = {"job": datetime.now().strftime("%Y%m%d-%H%M%S"), "kind": kind, "batch": batch,
                  "state": "running", "steps": steps, "step": None, "done": [],
                  "started": datetime.now().isoformat(timespec="seconds"), "finished": None,
                  "message": "", "outcome": None, "pid": os.getpid()}
        self.log = RUNNER / f"{self.s['job']}.log"
        self.s["log"] = self.log.name
        self.save()

    def save(self):
        tmp = STATUS.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.s, indent=1, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATUS)

    def step(self, name, *cmd):
        self.s["step"] = name
        self.save()
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(f"\n=== {name} ===\n")
            f.flush()
            if cmd:
                r = subprocess.run([sys.executable, *cmd], cwd=ROOT, stdout=f, stderr=subprocess.STDOUT,
                                   env={**os.environ, "PYTHONIOENCODING": "utf-8"})
                if r.returncode != 0:
                    raise RuntimeError(f"{name} failed (exit {r.returncode}); see {self.log.name}")
        self.s["done"].append(name)
        self.save()

    def finish(self, outcome, message):
        self.s.update(state="done", step=None, outcome=outcome, message=message,
                      finished=datetime.now().isoformat(timespec="seconds"))
        self.save()

    def fail(self, err):
        self.s.update(state="failed", message=str(err), finished=datetime.now().isoformat(timespec="seconds"))
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        self.save()


def new_batch_name():
    base = date.today().isoformat()
    name, n = base, 2
    while (ROOT / "work" / name).exists():
        name, n = f"{base}-{n}", n + 1
    return name


def py(script, *args):
    return (str(ROOT / "pipeline" / f"{script}.py"), *args)


def intake():
    photos = [p for p in (ROOT / "unsorted").iterdir() if p.suffix.lower() in EXTS]
    if not photos:
        raise SystemExit("no photos in unsorted/")
    batch = new_batch_name()
    job = Job("intake", batch, ["Convert photos", "Identify records", "Search Discogs", "Add pressing details",
                                "List possible pressings", "Build review"])
    try:
        job.step("Convert photos", *py("prep", batch))
        # Originals leave unsorted/ right away so the next intake never re-processes them.
        dest = ROOT / "processed" / batch
        dest.mkdir(parents=True, exist_ok=True)
        for p in json.loads((ROOT / "work" / batch / "photos.json").read_text()):
            src = ROOT / "unsorted" / p["source"]
            if src.exists():
                shutil.move(str(src), dest / p["source"])
        job.step("Identify records", *py("identify", batch))
        job.step("Search Discogs", *py("match", batch))
        job.step("Add pressing details", *py("enrich", batch))
        job.step("List possible pressings", *py("pool", batch))
        job.step("Build review", *py("build_review", batch))
        n = len(json.loads((ROOT / "work" / batch / "ident.json").read_text(encoding="utf-8")))
        job.finish("review", f"{n} records ready to review")
    except BaseException as e:
        job.fail(e)
        raise


def open_records(batch):
    """Records whose current round has no confirmed/final decision yet."""
    bdir = ROOT / "work" / batch
    idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
    dec = json.loads((bdir / "decisions.json").read_text(encoding="utf-8"))
    out = []
    for r in idents:
        d = dec.get(r["id"])
        if not d or d.get("round", 0) < r.get("round", 0):
            out.append(r["id"])
    return out


def finish(batch):
    bdir = ROOT / "work" / batch
    job = Job("finish", batch, ["Re-search edited & rejected", "Re-identify rejected photos", "Search again",
                                "Build review", "Export spreadsheet & CSV", "Add to Discogs collection"])
    try:
        unreviewed = open_records(batch)
        if unreviewed:
            job.finish("incomplete", f"{len(unreviewed)} records still need a decision: {', '.join(unreviewed)}")
            return
        job.step("Re-search edited & rejected", *py("research", batch))
        idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
        if any(r.get("needs_reident") for r in idents):
            job.step("Re-identify rejected photos", *py("identify", batch, "--reident"))
            idents = json.loads((bdir / "ident.json").read_text(encoding="utf-8"))
            for r in idents:  # never loop forever on a record Claude couldn't finish
                r.pop("needs_reident", None)
            (bdir / "ident.json").write_text(json.dumps(idents, indent=1, ensure_ascii=False), encoding="utf-8")
            job.step("Search again", *py("research", batch))
        reopened = open_records(batch)
        if reopened:
            job.step("Build review", *py("build_review", batch))
            job.finish("review", f"Re-searched {len(reopened)} records: {', '.join(reopened)}. Review them again.")
            return
        job.step("Export spreadsheet & CSV", *py("export", batch, "--move-photos"))
        job.step("Add to Discogs collection", *py("add_to_discogs", batch))
        tail = [l for l in job.log.read_text(encoding="utf-8").splitlines() if l.startswith(("added ", "would add"))]
        job.finish("imported", tail[-1] if tail else "Exported and added to Discogs")
    except BaseException as e:
        job.fail(e)
        raise


if __name__ == "__main__":
    {"intake": lambda: intake(), "finish": lambda: finish(sys.argv[2])}[sys.argv[1]]()
