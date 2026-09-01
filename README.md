# Jerusalem-Graffiti

Field photography of graffiti, posters and street art in Jerusalem, with the
coordinates of every shot.

Photos are captured with **[Timemark](https://play.google.com/store/apps/details?id=com.tools.gpsphoto)
on Android** (OnePlus CPH2493), which writes real EXIF GPS tags in addition to
its visible watermark. That EXIF is what makes the collection queryable — the
coordinate in the CSV is read out of the file, not transcribed off the picture.

## Layout

```
photos/<DDMM>/            # one folder per shooting day, day-first: 3108 = 31 August
  <original filenames>.jpg
  geolocations.csv        # generated, one row per photo
scripts/exif_to_csv.py    # the generator
.claude/skills/timemark-geo-csv/   # the same process, written for an agent
```

Folder names are **DDMM, day first**. Timemark's own filenames are ISO-dated, so
the full date is never actually ambiguous — the folder is a shorthand, not the
authority.

Original filenames are kept verbatim, spaces and parentheses included. They carry
the capture timestamp and Timemark's custom-field tags, and the CSV is keyed on
them.

## Batches

| Folder | Date | Photos | Subject | Area |
|---|---|---|---|---|
| [`photos/3108`](photos/3108) | 2026-08-31, 17:17–17:30 local (UTC+2) | 13 | Rebbe posters | Central Jerusalem, 31.7822–31.7841 N, 35.2159–35.2195 E |

The `3108` batch is a single walk: the coordinates move steadily north-west over
thirteen minutes, climbing from 815 m to 829 m. Two photos carry Timemark custom
fields (`Poster=Rebbe`, `Quantity=Single`); the other eleven were shot untagged.
Source zip was `Rebbe posters-1-001.zip`, a Google Drive export of the album.

## Rebuilding a CSV

```bash
python3 scripts/exif_to_csv.py photos/3108
```

Needs `exiftool` (`apt install libimage-exiftool-perl`). Writes
`photos/<DDMM>/geolocations.csv`, sorted by capture time, and warns on stderr
about any photo with no GPS tags.

Regenerate every folder at once:

```bash
for d in photos/*/; do python3 scripts/exif_to_csv.py "$d"; done
```

## CSV columns

| Column | Source |
|---|---|
| `filename` | on disk, unmodified |
| `captured_local` | EXIF `DateTimeOriginal` |
| `utc_offset` | EXIF `OffsetTimeOriginal` |
| `latitude`, `longitude` | EXIF `GPSLatitude` / `GPSLongitude`, decimal degrees, 7 dp |
| `altitude_m` | EXIF `GPSAltitude`, metres above sea level |
| `maps_url` | derived from lat/lon |
| `timemark_tags` | parsed from the filename, `Key=Value` pairs joined by `;` |
| `camera_make`, `camera_model`, `software` | EXIF |
| `width`, `height` | EXIF |

## What Timemark does, and where the data lives

Worked out by inspecting the 2026-08-31 batch; verified 2026-09-01.

- **GPS is real EXIF.** `GPSLatitude`, `GPSLongitude`, `GPSAltitude` and
  `GPSVersionID` are written as standard tags. Nothing needs to be read off the
  watermark to place a photo.
- **The street address is pixels only.** Timemark's watermark panel shows date,
  coordinates *and* a human-readable address. The address is burnt into the image
  and has no EXIF field — recovering it as text needs OCR or a vision model. The
  script does not attempt it.
- **Custom fields go in the filename**, appended as `(Key-Value)` groups:
  `2026-08-31 17.29.47__(Poster-Rebbe)_(Quantity-Single).jpg`. The doubled
  underscore is the app's separator for an empty leading field, not corruption.
- **`Software` is the fingerprint.** It reads `Timemark v10.0.210` and `Artist`
  reads `Timemark` — that is how to tell an app photo from a stock-camera one.
- **`UserComment` holds an opaque encrypted blob** (~10 KB of base64), presumably
  the app's tamper-evidence record. Not decoded here and not used.
- **File mtimes are download artefacts**, not capture times — the Drive export
  rewrites them. Trust `DateTimeOriginal`.

## Deliberately offline

`exif_to_csv.py` makes no network calls. Coordinates are not reverse-geocoded and
photos are not uploaded anywhere. Adding a street-name column would mean sending
every coordinate to a geocoding service; that is a decision to make explicitly,
not a default.

## Status

Working repo, scope still expanding. Adding a batch means: drop the photos into a
new `photos/<DDMM>/`, run the script, commit both. The
`.claude/skills/timemark-geo-csv` skill walks an agent through it, including
unpacking a fresh Drive zip.
