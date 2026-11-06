"""One-time setup: register the record-pipeline MCP server with the Claude desktop app.

Usage: python pipeline/setup_desktop_mcp.py
Adds "record-pipeline" under mcpServers in the desktop app's
claude_desktop_config.json (backing the file up first), so the Record Intake
artifact can reach it as host:record-pipeline. Restart the Claude app afterwards.
"""
import json
import os
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def config_path():
    if os.name == "nt":
        return Path(os.environ["APPDATA"]) / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def main():
    p = config_path()
    data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    if p.exists():
        backup = p.with_name(f"claude_desktop_config.backup-{datetime.now():%Y%m%d%H%M%S}.json")
        shutil.copy2(p, backup)
        print("backup:", backup)
    data.setdefault("mcpServers", {})["record-pipeline"] = {
        "command": sys.executable,
        "args": [str(ROOT / "pipeline" / "mcp_server.py")],
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print("added record-pipeline to", p)
    print("Now fully quit and reopen the Claude app.")


if __name__ == "__main__":
    main()
