---
name: poster-survey
description: Ingest a batch of Timemark field photos into this repo and produce the geolocation CSV and the Take-me-here field-sheet PDF. Use when a new zip of poster photos arrives (typically a Google Drive export named "<album>-1-001.zip"), when asked for coordinates or a CSV for a photo folder, when asked where a set of photos was taken, or when asked to build the PDF someone can follow in the street.
---

# Poster survey: photos in, CSV and field sheet out

Everything here is offline. No network calls, no reverse geocoding, no uploads.
Coordinates come out of EXIF, not off the watermark.

Images are published **unredacted**. Do not add face or plate blurring unless
asked; see `docs/vision-pipeline-on-hold.md` for why that work is parked.

## Repo layout

```
photos/<project>/<DDMM>/       # project, then capture day, day-first
  <original filenames>.jpg
  geolocations.csv             # generated from EXIF
posters.csv                    # the survey, hand-maintained tracking columns
config.json                    # reporter, defaults, allowed values
pdf/take-me-here.pdf
scripts/exif_to_csv.py | build_poster_list.py | build_pdf.py
templates/take-me-here.typ
```

The chain runs one way and every step is repeatable:

```
photos -> geolocations.csv -> posters.csv -> take-me-here.pdf
```

`posters.csv` is the source of truth. Never annotate the PDF; edit the CSV and
rebuild.

`3108` is 31 August. Keep Timemark's original filenames verbatim — they carry
the timestamp and the custom-field tags, and the CSV is keyed on them.

## Procedure

1. **Unpack and find the real capture day.**

   ```bash
   unzip -q "<zip>" -d /tmp/ingest
   find /tmp/ingest -type f
   exiftool -DateTimeOriginal "/tmp/ingest/<one file>.jpg"
   ```

   The zip name and the file mtimes are both download artefacts rewritten by the
   Drive export. Only `DateTimeOriginal` is trustworthy. If a batch spans two
   days, split it into two folders.

2. **File them** under `photos/<project>/<DDMM>/`, creating the project folder if
   this is a new campaign or subject.

3. **Build the CSV.**

   ```bash
   python3 scripts/exif_to_csv.py photos/<project>/<DDMM>
   ```

   Needs `exiftool` (`apt install libimage-exiftool-perl`). Warns on stderr about
   any photo with no GPS tags.

4. **Merge into the survey.**

   ```bash
   python3 scripts/build_poster_list.py
   ```

   Adds new rows with the defaults from `config.json` (`status=reported`,
   `reported_by`), and **preserves every hand-edited tracking column** on rows
   that already exist. It validates `status` / `condition` / `form` / `mounting`
   against the vocabularies and refuses to write if a value is off-list, so a
   typo fails loudly rather than silently becoming a new category.

   Then fill in what can be established by looking at the photographs:
   `poster_count`, `form`, `mounting`, `condition`. Leave anything uncertain as
   `unknown` rather than guessing — a wrong count is worse than a missing one.
   The `poster-image-review` subagent does this in batches and reports JSON;
   merge its findings yourself rather than letting it write the file.

   Where two frames share a GPS point, decide whether they show the **same**
   artwork or different artwork nearby, and set `duplicate_of` on the repeat.
   This cannot be inferred from the coordinate and it changes the totals: one
   pole shot twice must not count double, but four pieces around one corner
   must still add up.

5. **Build the field sheet.**

   ```bash
   python3 scripts/build_pdf.py --subtitle "<street>, <area>"
   ```

   Needs `typst`. Sections by capture day; each entry gets a *Take me here*
   button linking to Google Maps **directions**
   (`/maps/dir/?api=1&destination=`), not a map pin, plus a table of that
   poster's tracked status.

6. **Verify before reporting.** A written file is not proof of good data.

   ```bash
   column -s, -t < photos/<project>/<DDMM>/geolocations.csv | less -S
   python3 scripts/build_poster_list.py --check
   python3 -c "import re;d=open('pdf/<name>.pdf','rb').read();print(len(re.findall(rb'/URI\s*\(',d)),'links')"
   ```

   Check the coordinate columns are populated, that the points land where the
   photos were actually taken, that the row count matches the file count, and
   that the PDF's links are real URI annotations rather than styled text. Empty
   coordinates mean location was off at capture; say so rather than leaving
   blank cells unexplained.

7. **Commit** photos, both CSVs and the PDF together, and add a row to the Batches table
   in `README.md`.

## What Timemark writes, and where

Established from the 2026-08-31 batch, verified 2026-09-01.

- **GPS is genuine EXIF.** `GPSLatitude`, `GPSLongitude`, `GPSAltitude`.
- **The watermark shows time, date, `GMT+N` and coordinates — not a street
  address.** Some frames add a GPS accuracy figure (`±11m`, `±14m`) which has no
  EXIF equivalent and is only recoverable by reading the pixels. An earlier
  version of the docs claimed the watermark carried an address; that was
  inferred and wrong.
- **`OffsetTimeOriginal` is stale.** It reads `+02:00` on every frame while the
  watermark reads `GMT+3`, and Israel was on IDT. Treat `captured_local` as
  local wall-clock and ignore `utc_offset`.
- **Custom fields ride in the filename** as `(Key-Value)` groups, e.g.
  `2026-08-31 17.29.47__(Poster-Rebbe)_(Quantity-Single).jpg`. The doubled
  underscore is the app's separator for an empty leading field, not corruption.
- **`Software` is the fingerprint**: `Timemark v10.0.210`, `Artist` = `Timemark`.
- **`UserComment` is an opaque ~10 KB base64 blob**, presumably tamper-evidence.
  Not decoded, not used.

## Adding a CSV column

Edit `FIELDS` and `normalise()` in `scripts/exif_to_csv.py`, add the tag to the
`exiftool` call in `read_exif()`, then regenerate every batch so the CSVs stay
uniform:

```bash
for d in photos/*/*/; do python3 scripts/exif_to_csv.py "$d"; done
```
