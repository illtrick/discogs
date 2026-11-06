# Record intake pipeline

Turn phone photos of records into Discogs collection entries and a spreadsheet.

## Each new batch

1. Drop photos (HEIC/JPG) into `unsorted/`. A cover, back or label photo is fine; a barcode or catalog-number close-up is often best. Several photos taken in a row of the same record get grouped together.
2. Ask Claude: **"run the record pipeline"**. Claude will:
   - `python pipeline/prep.py <batch>`: convert the photos to `work/<batch>/photos/`
   - read each photo and write `work/<batch>/ident.json` (artist, title, label, catalog #, barcode, confidence)
   - `python pipeline/match.py <batch>`: search Discogs (barcode → catalog # → artist+title → album/master fallback) and save candidates and covers
   - `python pipeline/enrich.py <batch>`: add the details that tell pressings apart (vinyl color, release date, runout etchings, notes, have/want)
   - `python pipeline/pool.py <batch>`: list every pressing each record could be (from barcode, catalog # or all album versions), which drives the guided questions
   - `python pipeline/build_review.py <batch>`: build `review/` and republish the **Record Intake** review artifact
3. Review in the artifact: each card asks whether the album is right, then a few questions about your copy (vinyl color, catalog number, where it was made, runout etching…) until one pressing is left; confirm it. **Not sure** skips a question; **Edit** and **Reject** are always there. Keyboard: `J`/`K` move, `1`–`9` answer, `S` not sure, `B` back, `C` confirm, `E`/`R`, `U` undo.
4. Tell Claude you're done. Claude saves your decisions to `work/<batch>/decisions.json` and runs
   `python pipeline/research.py <batch>`, which re-searches every record you **edited** (using your artist/title/label/cat #) or **rejected** (excluding everything shown before; Claude re-reads the photos first). Those records come back as **To review** in the artifact. Repeat until nothing is edited or rejected, then Claude runs
   `python pipeline/export.py <batch> --move-photos`, which writes:
   - `export/<batch>_discogs_import.csv`: `release_id,Label,Title` for [discogs-import](https://github.com/guroot/discogs-import)
   - `collection.xlsx`: the running master list to import into Google Sheets (each batch's rows are replaced on re-export, so it is safe to re-run)
   - moves the originals to `processed/<batch>/`

## Stage 2: adding to Discogs

`python pipeline/add_to_discogs.py <batch>` adds the batch's releases to your collection (folder `collection_folder` in `config.ini`; 1 = Uncategorized) using the personal `token` and `username` there. It counts the copies you already own first and only adds the missing ones, so it is safe to re-run; `--dry-run` shows what it would do. Added instance ids go to `work/<batch>/added.json`.

## Files

| Path | What it is |
|---|---|
| `config.ini` | Discogs credentials. Keep it private. |
| `pipeline/` | The scripts |
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
