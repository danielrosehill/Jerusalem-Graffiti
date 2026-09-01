// Field sheet: one entry per photographed poster, each with a tappable
// directions link. Built for reading on a phone in the street, so the link
// target is Google Maps *directions*, not a map pin.
//
// Compile via scripts/build_pdf.py, which passes `batch` as a typst input.

#let batch = sys.inputs.at("batch")
#let subtitle = sys.inputs.at("subtitle", default: "")

#let rows = csv("/photos/" + batch + "/geolocations.csv", row-type: dictionary)

#set document(title: "Take me here - " + batch)
#set page(paper: "a4", margin: (x: 14mm, y: 14mm), numbering: "1 / 1")
#set text(font: ("DejaVu Sans", "IBM Plex Sans Hebrew"), size: 9pt)
#show link: set text(fill: rgb("#1a5fb4"))

#align(center)[
  #text(size: 17pt, weight: "bold")[Take me here]
  #v(-4pt)
  #text(size: 11pt)[#batch]
  #if subtitle != "" [ #v(-3pt) #text(size: 9pt, fill: luma(90))[#subtitle] ]
]
#v(4pt)
#line(length: 100%, stroke: 0.5pt + luma(180))
#v(2pt)

#text(size: 8pt, fill: luma(90))[
  #rows.len() locations. Coordinates read from each photo's EXIF GPS tags, not
  transcribed from the watermark. Times are local wall-clock; the EXIF UTC
  offset on this batch is stale and should be ignored. Tap *Take me here* for
  driving directions to the exact point.
]
#v(6pt)

#let entry(i, r) = {
  let dest = r.latitude + "," + r.longitude
  let dir = "https://www.google.com/maps/dir/?api=1&destination=" + dest
  let pin = "https://www.google.com/maps/search/?api=1&query=" + dest
  block(breakable: false, width: 100%, inset: (y: 5pt), stroke: (bottom: 0.4pt + luma(200)))[
    #grid(
      columns: (26%, 1fr),
      gutter: 10pt,
      image("/photos/" + batch + "/" + r.filename, width: 100%),
      [
        #text(size: 11pt, weight: "bold")[#(i + 1). #r.captured_local.slice(11)]
        #h(6pt)
        #text(size: 8pt, fill: luma(110))[#r.captured_local.slice(0, 10)]

        #v(1pt)
        #text(size: 9pt)[#r.latitude, #r.longitude #h(4pt) #text(fill: luma(120))[· #r.altitude_m m]]

        #if r.timemark_tags != "" [
          #v(1pt)
          #text(size: 8pt, fill: luma(110))[#r.timemark_tags]
        ]

        #v(4pt)
        #link(dir)[
          #box(fill: rgb("#1a5fb4"), inset: (x: 9pt, y: 5pt), radius: 3pt)[
            #text(fill: white, weight: "bold", size: 10pt)[Take me here]
          ]
        ]
        #h(8pt)
        #link(pin)[#text(size: 8pt)[view pin]]

        #v(3pt)
        #text(size: 6.5pt, fill: luma(150))[#r.filename]
      ],
    )
  ]
}

#for (i, r) in rows.enumerate() { entry(i, r) }
