"""Local MCP server (stdio) that lets the Record Intake artifact run the pipeline.

Registered in the Claude app as "record-pipeline"; the artifact calls it as host:record-pipeline.
Tools:
  status         read   photos waiting in unsorted/, the current/last job, batches
  get_batch      read   a batch's review data (records, candidates, pressing pools)
  get_image      read   one photo or Discogs cover for a batch
  start_intake   write  process the photos in unsorted/ into a new batch (runs in the background)
  finish_review  write  save the page's decisions, then re-search or export + add to Discogs
Only these fixed pipeline actions are exposed; inputs are validated and nothing else is run.
Pure standard library + Pillow; newline-delimited JSON-RPC over stdin/stdout.
"""
import base64
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "work"
STATUS = WORK / "_runner" / "status.json"
EXTS = {".heic", ".heif", ".jpg", ".jpeg", ".png"}
BATCH_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(-\d+)?$")
IMG_RE = re.compile(r"^(photos/(?P<b>[\w-]+)/(?P<p>p\d{3})\.jpg|covers/(?P<c>[rm]\d+)\.jpg)$")

TOOLS = [
    {"name": "status", "description": "Pipeline status: photos waiting, current or last job, batches.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": True}},
    {"name": "get_batch", "description": "Review data for one batch.",
     "inputSchema": {"type": "object", "properties": {"batch": {"type": "string"}}, "required": ["batch"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "get_image", "description": "A batch photo (photos/<batch>/pNNN.jpg) or cover (covers/rNNN.jpg) as JPEG.",
     "inputSchema": {"type": "object", "properties": {"batch": {"type": "string"}, "path": {"type": "string"}},
                     "required": ["batch", "path"]}, "annotations": {"readOnlyHint": True}},
    {"name": "start_intake", "description": "Process the photos in unsorted/ into a new review batch.",
     "inputSchema": {"type": "object", "properties": {}}, "annotations": {"readOnlyHint": False}},
    {"name": "finish_review",
     "description": "Save review decisions for a batch, then re-search edited/rejected records or, when all are "
                    "confirmed, export the spreadsheet/CSV and add the records to the Discogs collection.",
     "inputSchema": {"type": "object", "properties": {"batch": {"type": "string"},
                                                      "decisions": {"type": "object"}},
                     "required": ["batch", "decisions"]}, "annotations": {"readOnlyHint": False}},
]


class ToolError(Exception):
    pass


def read_json(p, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def pid_alive(pid):
    if not pid:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(h)
        return code.value == 259  # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
        return True
    except OSError:
        return False


def job_status():
    s = read_json(STATUS)
    if s and s.get("state") == "running" and not pid_alive(s.get("pid")):
        s["state"] = "failed"
        s["message"] = s.get("message") or "The runner stopped unexpectedly."
    if s and s.get("log"):
        try:
            lines = (WORK / "_runner" / s["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
            s["log_tail"] = lines[-12:]
        except OSError:
            s["log_tail"] = []
    return s


def batch_dir(batch):
    if not isinstance(batch, str) or not BATCH_RE.match(batch) or not (WORK / batch).is_dir():
        raise ToolError(f"unknown batch: {batch!r}")
    return WORK / batch


def batches():
    out = []
    for d in sorted((p for p in WORK.iterdir() if p.is_dir() and BATCH_RE.match(p.name)), reverse=True):
        if (d / "batch.json").exists() or (d / "ident.json").exists():
            out.append({"batch": d.name, "ready": (d / "batch.json").exists(),
                        "exported": (ROOT / "export" / f"{d.name}_discogs_import.csv").exists(),
                        "added": (d / "added.json").exists()})
    return out


def spawn(*args):
    job = job_status()
    if job and job.get("state") == "running":
        raise ToolError(f"A {job.get('kind')} job is already running ({job.get('step')}).")
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDECODE", "CLAUDE_", "ANTHROPIC_"))}
    cmd = [sys.executable, str(ROOT / "pipeline" / "run.py"), *args]
    kw = dict(cwd=ROOT, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
              stderr=subprocess.DEVNULL, close_fds=True)
    try:  # break away from the app's job object so the run survives an app restart
        p = subprocess.Popen(cmd, creationflags=flags | (0x01000000 if os.name == "nt" else 0), **kw)
    except OSError:
        p = subprocess.Popen(cmd, creationflags=flags, **kw)
    return {"started": True, "pid": p.pid}


def call(name, a):
    if name == "status":
        unsorted = [p.name for p in (ROOT / "unsorted").iterdir() if p.suffix.lower() in EXTS] \
            if (ROOT / "unsorted").exists() else []
        return {"unsorted": len(unsorted), "job": job_status(), "batches": batches()}
    if name == "get_batch":
        data = read_json(batch_dir(a.get("batch")) / "batch.json")
        if data is None:
            raise ToolError("this batch has no review data yet")
        return data
    if name == "get_image":
        bdir = batch_dir(a.get("batch"))
        m = IMG_RE.match(a.get("path") or "")
        if not m:
            raise ToolError("bad image path")
        f = bdir / "photos" / f"{m['p']}.jpg" if m["p"] else bdir / "covers" / f"{m['c']}.jpg"
        if not f.exists():
            raise ToolError("image not found")
        from PIL import Image
        im = Image.open(f)
        im.thumbnail((900, 900))
        buf = io.BytesIO()
        im.convert("RGB").save(buf, "JPEG", quality=78)
        return {"__image__": base64.b64encode(buf.getvalue()).decode()}
    if name == "start_intake":
        if not any(p.suffix.lower() in EXTS for p in (ROOT / "unsorted").iterdir()):
            raise ToolError("There are no photos in the unsorted folder.")
        return spawn("intake")
    if name == "finish_review":
        bdir = batch_dir(a.get("batch"))
        dec = a.get("decisions")
        if not isinstance(dec, dict):
            raise ToolError("decisions must be an object keyed by record id")
        clean = {}
        for rid, d in dec.items():
            if re.match(r"^r\d{2,3}$", rid) and isinstance(d, dict) and d.get("status") in ("confirmed", "edited", "rejected"):
                clean[rid] = d
        (bdir / "decisions.json").write_text(json.dumps(clean, indent=1, ensure_ascii=False), encoding="utf-8")
        return {**spawn("finish", bdir.name), "decisions": len(clean)}
    raise ToolError(f"unknown tool {name}")


def reply(id_, result=None, error=None):
    msg = {"jsonrpc": "2.0", "id": id_}
    msg["error" if error else "result"] = error or result
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            continue
        method, id_ = req.get("method"), req.get("id")
        if id_ is None:
            continue  # notification
        if method == "initialize":
            reply(id_, {"protocolVersion": (req.get("params") or {}).get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "record-pipeline", "version": "1.0"}})
        elif method == "ping":
            reply(id_, {})
        elif method == "tools/list":
            reply(id_, {"tools": TOOLS})
        elif method == "tools/call":
            p = req.get("params") or {}
            try:
                out = call(p.get("name"), p.get("arguments") or {})
                if isinstance(out, dict) and "__image__" in out:
                    reply(id_, {"content": [{"type": "image", "data": out["__image__"], "mimeType": "image/jpeg"}]})
                else:
                    reply(id_, {"content": [{"type": "text", "text": json.dumps(out, ensure_ascii=False)}],
                                "structuredContent": out})
            except ToolError as e:
                reply(id_, {"content": [{"type": "text", "text": str(e)}], "isError": True})
            except Exception as e:  # keep the server alive
                reply(id_, {"content": [{"type": "text", "text": f"internal error: {e}"}], "isError": True})
        else:
            reply(id_, error={"code": -32601, "message": f"method not found: {method}"})


if __name__ == "__main__":
    main()
