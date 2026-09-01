---
name: timemark-geo-csv
description: Build a geolocation CSV from a folder of photos taken with Timemark on Android. Use when the user drops a new batch of field photos into this repo, asks for a CSV of coordinates for a photo folder, or asks where a set of photos was taken. Also covers ingesting a Google Drive/Takeout zip of Timemark photos into the repo's DDMM folder layout.
---

# Timemark photos → geolocation CSV

Turns a folder of Timemark field photos into `geolocations.csv` alongside them.
Everything comes out of EXIF. **No network calls** — do not reverse-geocode,
call a maps API, or upload the photos anywhere unless the user asks in that turn.

## Repo layout this assumes

```
photos/<DDMM>/            # day of capture, day-first: 3108 = 31 August
  <original filenames>.jpg
  geolocations.csv        # generated, one row per photo
scripts/exif_to_csv.py    # the generator
```

One folder per shooting day. Keep Timemark's original filenames — they carry the
timestamp and the custom-field tags, and the CSV is keyed on them.

## Procedure

1. **Ingest**, if starting from a zip (Timemark exports via Google Drive, so the
   download is usually `<album name>-1-001.zip` with one folder inside):

   ```bash
   unzip -q "<zip>" -d /tmp/ingest
   find /tmp/ingest -type f        # confirm what actually came out
   ```

   Read `DateTimeOriginal` off one file to get the real capture day — the zip
   name and the file mtimes are both download artefacts and will mislead you.

2. **Create the folder** `photos/<DDMM>/` for that capture day and copy the
   images in. If photos in one batch span two days, split them into two folders.

3. **Generate the CSV**:

   ```bash
   python3 scripts/exif_to_csv.py photos/<DDMM>
   ```

   Requires `exiftool` (Debian/Ubuntu: `apt install libimage-exiftool-perl`).
   It writes `photos/<DDMM>/geolocations.csv` and warns on stderr about any file
   with no GPS tags.

4. **Verify before reporting.** A written CSV is not proof of good data:

   ```bash
   column -s, -t < photos/<DDMM>/geolocations.csv | less -S
   ```

   Check the latitude/longitude columns are populated, that the coordinates land
   where the user says they were shot, and that the row count matches the file
   count. Empty coordinate columns mean location was off when the photo was
   taken; say so rather than leaving blank cells unexplained.

5. **Commit** the photos and the CSV together.

## What Timemark puts where

- **EXIF GPS tags** — `GPSLatitude`, `GPSLongitude`, `GPSAltitude` are written as
  standard EXIF. This is the machine-readable source and the only one the script
  reads.
- **A burnt-in watermark** — Timemark also stamps a panel onto the image pixels
  with the date, coordinates and a **street address**. The address exists *only*
  in the pixels; there is no EXIF field for it. Extracting it needs OCR or a
  vision model reading the image, which this script deliberately does not do.
- **Filename tags** — Timemark's custom fields are appended as `(Key-Value)`
  groups, e.g. `2026-08-31 17.29.47__(Poster-Rebbe)_(Quantity-Single).jpg`. The
  script parses these into the `timemark_tags` column as `Poster=Rebbe;Quantity=Single`.
  Untagged photos get an empty cell. The doubled underscore is Timemark's
  separator for an empty leading field, not a parse error.
- `Software` reads `Timemark v<version>` and `Artist` reads `Timemark`, which is
  how to confirm a photo came from the app rather than the stock camera.

## CSV columns

`filename`, `captured_local`, `utc_offset`, `latitude`, `longitude`,
`altitude_m`, `maps_url`, `timemark_tags`, `camera_make`, `camera_model`,
`software`, `width`, `height`.

Rows are sorted by capture time. Coordinates are decimal degrees to 7 dp.

## Adding a column

Edit `FIELDS` and `normalise()` in `scripts/exif_to_csv.py`, add the EXIF tag to
the `exiftool` argument list in `read_exif()`, then regenerate every folder so
the CSVs stay uniform:

```bash
for d in photos/*/; do python3 scripts/exif_to_csv.py "$d"; done
```
