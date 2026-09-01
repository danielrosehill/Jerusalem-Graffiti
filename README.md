# Jerusalem-Graffiti

Field photography of a messianic postering campaign in central Jerusalem, with
the coordinates of every shot.

Portraits of the Lubavitcher Rebbe captioned **יחי המלך המשיח** ("long live the
King Messiah") are being pasted onto construction hoardings, lampposts and
street furniture along and around Jaffa Road. They appear in two physical forms:
large wheatpasted sheets, and small yellow stickers. This repository records
where they are, so the locations can be reported.

The municipal helpline (106) has not acted on reports, and a local group
concerned with religious messaging in shared public space has asked people to
document sightings. That is what this is for.

Images are published **as shot** — no faces or number plates are redacted.

## Layout

```
photos/<project>/<DDMM>/      # project, then day of capture, day-first
  <original filenames>.jpg
  geolocations.csv            # generated, one row per photo
scripts/exif_to_csv.py        # the generator
```

Folder names are **DDMM, day first**: `3108` is 31 August. Timemark's own
filenames are ISO-dated, so the full date is never actually ambiguous.

Original filenames are kept verbatim, spaces and parentheses included. They
carry the capture timestamp and Timemark's custom-field tags, and the CSV is
keyed on them.

## Batches

| Folder | Date | Photos | Subject | Area |
|---|---|---|---|---|
| [`photos/rebbe-posters/3108`](photos/rebbe-posters/3108) | 2026-08-31, 17:17–17:30 local | 13 | Rebbe posters and stickers | Central Jerusalem, 31.7822–31.7841 N, 35.2159–35.2195 E |

A single walk: the coordinates move steadily north-west over thirteen minutes,
climbing from 815 m to 829 m. Landmarks visible in frame place it on Jaffa Road
— the light rail track and a tram are in `17.26.18`. Source zip was
`Rebbe posters-1-001.zip`, a Google Drive export of the album.

Two photos carry Timemark custom fields (`Poster=Rebbe`, `Quantity=Single`); the
other eleven were shot untagged.

At least one sticker (the lower of the pair on the lamppost in `17.17.20`) has
been over-sprayed with black paint, which is worth noting as a separate state
from weathering: it means someone has already taken counter-action there.

## Rebuilding a CSV

```bash
python3 scripts/exif_to_csv.py photos/rebbe-posters/3108
```

Needs `exiftool` (`apt install libimage-exiftool-perl`). Writes
`geolocations.csv` beside the photos, sorted by capture time, and warns on
stderr about any photo with no GPS tags.

## CSV columns

| Column | Source |
|---|---|
| `filename` | on disk, unmodified |
| `captured_local` | EXIF `DateTimeOriginal` |
| `utc_offset` | EXIF `OffsetTimeOriginal` — **unreliable, see below** |
| `latitude`, `longitude` | EXIF GPS, decimal degrees, 7 dp |
| `altitude_m` | EXIF `GPSAltitude`, metres above sea level |
| `maps_url` | derived from lat/lon |
| `timemark_tags` | parsed from the filename, `Key=Value` joined by `;` |
| `camera_make`, `camera_model`, `software` | EXIF |
| `width`, `height` | EXIF |

## What Timemark writes, and where

Established by inspecting the 2026-08-31 batch. Verified 2026-09-01.

- **GPS is real EXIF.** `GPSLatitude`, `GPSLongitude` and `GPSAltitude` are
  written as standard tags, so a photo can be placed without reading the
  watermark.
- **The watermark carries time, date and coordinates — not a street address.**
  An earlier version of this file claimed it showed an address; that was
  inferred and is wrong. The burnt-in panel reads `HH:MM`, `GMT+N`, the date,
  the weekday, and `Coordinate: <lat>°N, <lon>°E`. Some frames add an accuracy
  figure (`±11m`, `±14m`) which has no EXIF equivalent and is only recoverable
  by reading the pixels.
- **The EXIF UTC offset is wrong.** `OffsetTimeOriginal` reads `+02:00` on every
  frame, while the watermark reads `GMT+3`. Israel was on IDT (UTC+3) on
  2026-08-31, so the watermark is right and the EXIF field is stale. Treat
  `captured_local` as local wall-clock time and ignore `utc_offset`.
- **Custom fields ride in the filename** as `(Key-Value)` groups:
  `2026-08-31 17.29.47__(Poster-Rebbe)_(Quantity-Single).jpg`. The doubled
  underscore is the app's separator for an empty leading field, not corruption.
- **`Software` is the fingerprint**, reading `Timemark v10.0.210`, with `Artist`
  set to `Timemark`. That distinguishes an app photo from a stock-camera one.
- **`UserComment` holds an opaque ~10 KB base64 blob**, presumably the app's
  tamper-evidence record. Not decoded, not used.
- **File mtimes are download artefacts**, rewritten by the Drive export. Only
  `DateTimeOriginal` is trustworthy.

## Deliberately offline

`exif_to_csv.py` makes no network calls. Coordinates are not reverse-geocoded.
Adding a street-name column would mean sending every coordinate to a geocoding
service, which is a decision to make explicitly rather than by default.

## History

A local computer-vision preprocessing pipeline (poster detection by ORB feature
matching, face and number-plate redaction via YuNet and colour heuristics) was
built and then removed on 2026-09-01, because the images are published
unredacted and the detection was not accurate enough to be worth maintaining.
It is recoverable from git history at commit `f6457d3` if ever wanted. The short
version of what was learned: exemplar feature matching reached roughly 45%
recall on these posters and failed entirely on small or shadowed instances,
whereas open-vocabulary detection (OWLv2, image-guided) localised the same
sticker accurately but over-generalised to other pole-mounted flyers.
