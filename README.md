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

## Toolkit — if you want to help

More sightings are welcome. The survey depends on photographs that carry their
own coordinates, so the capture app matters more here than the camera does.

**Timemark** — <https://www.timemark.com/>

- **Android** — [Play Store](https://play.google.com/store/apps/details?id=com.oceangalaxy.camera.new&referrer=utm_source%253Dweb%2526utm_medium%253Dwebflowsite) (package `com.oceangalaxy.camera.new`)
- **iOS** — [App Store](https://apps.apple.com/us/app/timemark-photo-proof-for-work/id6446071834)

It writes genuine EXIF GPS tags alongside its visible watermark, and that is
what makes a photograph usable here: the coordinate in the CSV is read out of
the file, not transcribed off the picture. A screenshot of a Timemark photo
keeps the watermark but loses the EXIF, so it is no use — send the original.

To contribute a sighting:

1. Shoot it with Timemark, location on.
2. Include enough of the surroundings to show what it is mounted on — lamppost,
   hoarding, wall, utility box.
3. If artwork has been sprayed over, torn or pasted over, photograph that too.
   Those states are tracked separately from intact ones, because they record
   that someone has already acted.
4. Send the album as a zip; the export from Google Drive is fine as-is.

## Layout

```
photos/<project>/<DDMM>/           # project, then day of capture, day-first
  <original filenames>.jpg
  geolocations.csv                 # generated from EXIF, one row per photo
posters.csv                        # the survey: tracked status per poster
config.json                        # reporter name, defaults, allowed values
pdf/take-me-here.pdf               # generated field sheet
scripts/exif_to_csv.py             # photos      -> geolocations.csv
scripts/build_poster_list.py       # geolocations -> posters.csv
scripts/build_pdf.py               # posters.csv -> PDF
templates/take-me-here.typ
docs/
.claude/skills/poster-survey/      # the whole procedure, written for an agent
```

The chain is one-directional, and each step is repeatable:

```
photos  ->  geolocations.csv  ->  posters.csv  ->  take-me-here.pdf
            (EXIF, machine)       (tracking, hand-edited)   (render)
```

`posters.csv` is the source of truth. The PDF is a pure render of it — never
annotate the PDF, edit the CSV and rebuild.

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

## Field sheet

[`pdf/take-me-here.pdf`](pdf/take-me-here.pdf) — sectioned by the day the
photographs were taken. Each entry carries a thumbnail, the coordinates, a
tappable **Take me here** button and a table of that poster's tracked status.
Built to be opened on a phone by someone actually going to the location, so the
button links to Google Maps *directions* (`/maps/dir/?api=1&destination=`), not
a map pin; a smaller link drops a pin instead.

```bash
python3 scripts/build_pdf.py --subtitle "Jaffa Road, central Jerusalem"
python3 scripts/build_pdf.py --project rebbe-posters     # limit to one project
```

Needs `typst`. Rebuild after every edit to `posters.csv`.

## Tracking: posters.csv

One row per photograph, keyed on a stable `id` built from the capture time, so
inserting or removing a photo never reassigns another row's identity.

Columns up to `timemark_tags` are **generated** from EXIF and overwritten on
every rebuild. Columns from `poster_count` onward are **hand-maintained and
preserved** — rebuilding merges rather than overwrites, so edits survive.

| Column | Values |
|---|---|
| `status` | `unknown`, `reported`, `removed`, `present` |
| `condition` | `unknown`, `intact`, `sprayed`, `torn`, `faded`, `overpasted` |
| `form` | `unknown`, `wheatpaste`, `sticker`, `mixed` |
| `mounting` | `unknown`, `hoarding`, `lamppost`, `wall`, `utility-box`, `bus-shelter`, `door`, `other` |
| `poster_count` | integer, blank if not counted |
| `reported_date`, `reported_by`, `report_ref`, `notes` | free text |

`sprayed` is deliberately distinct from `faded` or `torn`: it means someone has
already taken counter-action at that location, which is a different fact from
weathering.

New rows default to `status=reported` with `reported_by` and the vocabularies
set in [`config.json`](config.json). Rebuild validates every value against those
lists and refuses to write on a typo:

```bash
python3 scripts/build_poster_list.py            # merge and write
python3 scripts/build_poster_list.py --check    # validate only, exit 1 on problems
```

Five rows carry `form` / `mounting` / `condition` / `poster_count` confirmed by
looking at the images at full resolution. The remaining eight are `unknown`
rather than guessed.

## Rebuilding a CSV

```bash
python3 scripts/exif_to_csv.py photos/rebbe-posters/3108
```

Needs `exiftool` (`apt install libimage-exiftool-perl`). Writes
`geolocations.csv` beside the photos, sorted by capture time, and warns on
stderr about any photo with no GPS tags.

## geolocations.csv columns

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

## Work on hold

A local computer-vision pipeline (poster detection, face and number-plate
redaction) was built and then removed on 2026-09-01, because the images are
published unredacted and the detection was not accurate enough to maintain for
counting alone. It is **on hold, not abandoned**.

Everything learned is written up in
[`docs/vision-pipeline-on-hold.md`](docs/vision-pipeline-on-hold.md) — what
worked, the measured recall, the bugs that cost real time, and the better
architecture to start from if it resumes. Read that before rebuilding any of it.
Code is recoverable at commit `f6457d3`.

