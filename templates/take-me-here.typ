// Field sheet, generated from posters.csv. Never edit this output by hand --
// edit posters.csv and re-run scripts/build_pdf.py.
//
// Grouped into sections by the day the photographs were taken. Each entry gets
// a tappable directions link and a table of its tracked status, so the sheet is
// the working document: read it in the street, act, then update the CSV.

#let project = sys.inputs.at("project", default: "")
#let subtitle = sys.inputs.at("subtitle", default: "")

#let all = csv("/posters.csv", row-type: dictionary)
#let rows = if project == "" { all } else { all.filter(r => r.project == project) }
#let days = rows.map(r => r.captured_date).dedup()

#let pretty(d) = {
  let p = d.split("-")
  datetime(year: int(p.at(0)), month: int(p.at(1)), day: int(p.at(2)))
    .display("[weekday] [day] [month repr:long] [year]")
}
#let dash(v) = if v == "" { text(fill: luma(160))[--] } else { v }

#set document(title: "Take me here")
#set page(paper: "a4", margin: (x: 13mm, y: 13mm), numbering: "1 / 1")
#set text(font: ("DejaVu Sans", "IBM Plex Sans Hebrew"), size: 9pt)
#show link: set text(fill: rgb("#1a5fb4"))

#align(center)[
  #text(size: 18pt, weight: "bold")[Take me here]
  #v(-5pt)
  #text(size: 10pt, fill: luma(80))[
    #if project != "" [#project #sym.dot.c ] #rows.len() locations across #days.len() day#if days.len() != 1 [s]
  ]
  #if subtitle != "" [ #v(-4pt) #text(size: 9pt, fill: luma(110))[#subtitle] ]
]
#v(3pt)
#line(length: 100%, stroke: 0.5pt + luma(170))
#v(3pt)

#text(size: 7.5pt, fill: luma(100))[
  Generated from `posters.csv`; do not annotate this PDF -- edit the CSV and
  rebuild. Coordinates are read from each photo's EXIF GPS tags, not transcribed
  from the watermark. Times are local wall-clock. Tap *Take me here* for driving
  directions to the exact point.
]
#v(5pt)

#let entry(n, r) = block(breakable: false, width: 100%, inset: (y: 5pt),
                         stroke: (bottom: 0.4pt + luma(210)))[
  #grid(
    columns: (23%, 1fr),
    gutter: 9pt,
    image("/" + r.photo, width: 100%),
    [
      #text(size: 11pt, weight: "bold")[#n. #r.captured_time]
      #h(5pt)
      #text(size: 8.5pt)[#r.latitude, #r.longitude]
      #h(4pt)
      #text(size: 8pt, fill: luma(130))[#sym.dot.c #r.altitude_m m]

      #v(3pt)
      #link(r.directions_url)[
        #box(fill: rgb("#1a5fb4"), inset: (x: 9pt, y: 4pt), radius: 3pt)[
          #text(fill: white, weight: "bold", size: 9.5pt)[Take me here]
        ]
      ]
      #h(7pt)
      #link(r.maps_url)[#text(size: 8pt)[view pin]]

      #v(4pt)
      #table(
        columns: (auto, auto, auto, auto, auto, auto),
        inset: (x: 5pt, y: 3pt),
        stroke: 0.35pt + luma(205),
        align: left,
        table.header(
          ..([Status], [Condition], [Form], [Mounting], [Posters], [Reported]).map(
            c => text(size: 7pt, weight: "bold", fill: luma(70))[#c])
        ),
        ..(r.status, r.condition, r.form, r.mounting, r.poster_count, r.reported_date).map(
          v => text(size: 8pt)[#dash(v)]),
      )

      #if r.notes != "" [
        #v(2pt)
        #text(size: 7.5pt, fill: luma(95))[#r.notes]
      ]
      #v(2pt)
      #text(size: 6.5pt, fill: luma(155))[#r.id]
    ],
  )
]

#for day in days {
  let day_rows = rows.filter(r => r.captured_date == day)
  block(breakable: false, above: 10pt, below: 5pt)[
    #text(size: 13pt, weight: "bold")[#pretty(day)]
    #h(6pt)
    #text(size: 9pt, fill: luma(120))[#day_rows.len() location#if day_rows.len() != 1 [s]]
    #v(-3pt)
    #line(length: 100%, stroke: 1pt + rgb("#1a5fb4"))
  ]
  for (i, r) in day_rows.enumerate() { entry(i + 1, r) }
}
