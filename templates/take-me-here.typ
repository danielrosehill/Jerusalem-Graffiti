// Field sheet, generated from posters.csv. Never edit this output by hand --
// edit posters.csv and re-run scripts/build_pdf.py.
//
// One entry per LOCATION, not per photograph. Several frames often share one
// GPS point, and sending someone to the same lamppost four times would waste
// the trip. Extra frames of a location appear as supporting thumbnails.

#let project = sys.inputs.at("project", default: "")
#let subtitle = sys.inputs.at("subtitle", default: "")

#let all = csv("/posters.csv", row-type: dictionary)
#let rows = if project == "" { all } else { all.filter(r => r.project == project) }
#let days = rows.map(r => r.captured_date).dedup()
#let n_loc = rows.map(r => r.location_id).dedup().len()

#let pretty(d) = {
  let p = d.split("-")
  datetime(year: int(p.at(0)), month: int(p.at(1)), day: int(p.at(2)))
    .display("[weekday] [day] [month repr:long] [year]")
}
// Distinct, meaningful values only: "unknown" is noise once a real value exists.
#let joinu(vals) = {
  let v = vals.dedup().filter(x => x != "" and x != "unknown")
  if v.len() == 0 { "unknown" } else { v.join(" / ") }
}

#set document(title: "Take me here")
#set page(paper: "a4", margin: (x: 13mm, y: 13mm), numbering: "1 / 1")
#set text(font: ("DejaVu Sans", "IBM Plex Sans Hebrew"), size: 9pt)
#show link: set text(fill: rgb("#1a5fb4"))

#align(center)[
  #text(size: 18pt, weight: "bold")[Take me here]
  #v(-5pt)
  #text(size: 10pt, fill: luma(80))[
    #if project != "" [#project #sym.dot.c ]
    #n_loc locations #sym.dot.c #rows.len() photographs
  ]
  #if subtitle != "" [ #v(-4pt) #text(size: 9pt, fill: luma(110))[#subtitle] ]
]
#v(3pt)
#line(length: 100%, stroke: 0.5pt + luma(170))
#v(3pt)

#text(size: 7.5pt, fill: luma(100))[
  Generated from `posters.csv`; do not annotate this PDF -- edit the CSV and
  rebuild. Coordinates come from each photo's EXIF GPS tags. One entry per
  location: where several frames share a GPS point they are grouped, and a
  poster total marked *+* means at least that many, with some artwork present
  but not reliably countable. Tap *Take me here* for driving directions.
]
#v(5pt)

#let entry(n, group) = {
  let r = group.at(0)
  block(breakable: false, width: 100%, inset: (y: 5pt),
        stroke: (bottom: 0.4pt + luma(210)))[
    #grid(
      columns: (25%, 1fr),
      gutter: 9pt,
      [
        #image("/" + r.photo, height: 38mm)
        #if group.len() > 1 [
          #v(2pt)
          #grid(
            columns: group.slice(1).map(_ => 1fr),
            gutter: 2pt,
            ..group.slice(1).map(x => image("/" + x.photo, height: 12mm)),
          )
        ]
      ],
      [
        #text(size: 11pt, weight: "bold")[#n. #r.captured_time]
        #h(4pt)
        #text(size: 8pt, fill: luma(130))[#r.location_id]
        #if group.len() > 1 [
          #h(3pt) #text(size: 8pt, fill: luma(130))[#sym.dot.c #group.len() frames]
        ]

        #v(1pt)
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
          columns: (auto, auto, auto, auto, auto),
          inset: (x: 5pt, y: 3pt),
          stroke: 0.35pt + luma(205),
          align: left,
          table.header(
            ..([Posters], [Condition], [Form], [Mounting], [Reported]).map(
              c => text(size: 7pt, weight: "bold", fill: luma(70))[#c])
          ),
          ..(
            r.location_posters,
            joinu(group.map(x => x.condition)),
            joinu(group.map(x => x.form)),
            joinu(group.map(x => x.mounting)),
            r.reported_date,
          ).map(v => text(size: 8pt)[#v]),
        )

        #for x in group {
          if x.notes != "" [
            #v(2pt)
            #text(size: 7.5pt, fill: luma(95))[
              #text(fill: luma(140))[#x.captured_time#if x.duplicate_of != "" [ (repeat)]] #x.notes
            ]
          ]
        }
      ],
    )
  ]
}

#for day in days {
  let day_rows = rows.filter(r => r.captured_date == day)
  let locs = day_rows.map(r => r.location_id).dedup()
  block(breakable: false, above: 10pt, below: 5pt)[
    #text(size: 13pt, weight: "bold")[#pretty(day)]
    #h(6pt)
    #text(size: 9pt, fill: luma(120))[
      #locs.len() location#if locs.len() != 1 [s] #sym.dot.c #day_rows.len() photographs
    ]
    #v(-3pt)
    #line(length: 100%, stroke: 1pt + rgb("#1a5fb4"))
  ]
  for (i, loc) in locs.enumerate() {
    entry(i + 1, day_rows.filter(r => r.location_id == loc))
  }
}
