# Record intake pipeline

Turn phone photos of records into Discogs collection entries and a spreadsheet.

## Each new batch (from the artifact)

1. Drop photos (HEIC/JPG) into `unsorted/`. A cover, back or label photo is fine; a barcode or catalog-number close-up is often best. Photos taken in a row of the same record get grouped together.
2. Open the **Record Intake** artifact in the Claude desktop app and press **Process N new photos** in the Pipeline panel. It runs, in the background:
   - `prep.py`: convert photos to `work/<batch>/photos/` and move the originals to `processed/<batch>/`
   - `identify.py`: Claude Code (headless, `claude -p`) reads every photo and writes `work/<batch>/ident.json`, checking Discogs with `search.py`
   - `match.py` → `enrich.py` → `pool.py`: find candidates and every pressing each record could be
   - `build_review.py`: the review data the artifact loads
3. Review each card: confirm the album, answer a few questions until one pressing is left, confirm. **Edit** and **Reject** are always there. Keys: `J`/`K` move, `1`–`9` answer, `S` not sure, `B` back, `C` confirm, `E`/`R`, `U` undo.
4. Press **Finish review**. If you edited or rejected anything, `research.py` re-searches those records (rejected ones are re-identified from the photos, excluding everything shown before) and they come back as **To review**. When everything is confirmed, the same button runs `export.py` (CSV for [discogs-import](https://github.com/guroot/discogs-import) + `collection.xlsx`) and `add_to_discogs.py`.

Everything is driven by `pipeline/run.py intake` and `pipeline/run.py finish <batch>`, which you can also run by hand. Progress goes to `work/_runner/`.

### One-time setup for the Run buttons

The artifact reaches this folder through a small local MCP server, `pipeline/mcp_server.py` (standard library + Pillow). It exposes only fixed pipeline actions: status, read a batch or image, start intake, finish review.

1. Register it with Claude (user scope):
   `claude mcp add --scope user record-pipeline -- <path-to-python> <path-to-repo>/pipeline/mcp_server.py`
2. Make sure the standalone Claude Code CLI is signed in (`claude auth login`). `identify.py` uses it.
3. Restart the Claude desktop app, then open the artifact there. Run buttons only work in the desktop app, on this computer.

## Stage 2: adding to Discogs

`python pipeline/add_to_discogs.py <batch>` adds the batch's releases to your collection (folder `collection_folder` in `config.ini`; 1 = Uncategorized) using the personal `token` and `username` there. It counts the copies you already own first and only adds the missing ones, so it is safe to re-run; `--dry-run` shows what it would do. Added instance ids go to `work/<batch>/added.json`.

## Files

| Path | What it is |
|---|---|
| `config.ini` | Discogs credentials. Keep it private. |
| `pipeline/` | The scripts (`run.py` orchestrates; `mcp_server.py` connects the artifact) |
| `work/<batch>/` | Working data per batch (converted photos, identifications, matches, decisions) |
| `review/` | The published review artifact (page, batch.json, photos, covers) |
| `export/` | CSVs for import |
| `collection.xlsx` | Master list |

## Setup

```
pip install -r requirements.txt
cp config.example.ini config.ini   # then fill in your Discogs credentials
```

`config.ini`, photos (`unsorted/`, `processed/`, `work/*/photos/`) and Discogs cover images are git-ignored and never committed.

## Credits

- [Discogs API](https://www.discogs.com/developers): all release, master and pressing data. Discogs' release data is CC0; cover images belong to their owners and aren't stored in this repo.
- [guroot/discogs-import](https://github.com/guroot/discogs-import): the export CSV (`release_id,Label,Title`) follows its import format. None of its code is included here.
- [Pillow](https://python-pillow.org/) and [pillow-heif](https://github.com/bigcat88/pillow_heif): photo conversion. [openpyxl](https://openpyxl.readthedocs.io/): the spreadsheet.
- Written with [Claude Code](https://claude.com/claude-code). Photo identification runs through Claude Code in headless mode.
