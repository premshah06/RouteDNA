// One compact glyph per item category, so a package reads as "what it
// is" at a glance instead of an anonymous dot — used both by
// PackageIcon (lane chips) and the belt-canvas traveler in LiveView.
// Categories per proto/packagepb/v1/item.proto's ItemCategory enum.
export const PACKAGE_GLYPHS: Record<number, string> = {
  0: "M4,4 L12,4 L12,12 L4,12 Z", // UNSPECIFIED — plain box outline
  1: "M3,5 L13,5 L13,11 L3,11 Z M6,5 L6,3 L10,3 L10,5", // ELECTRONICS — device w/ port
  2: "M8,2 L5,4 L5,13 L11,13 L11,4 Z M5,4 L2,6 L3,8 L5,6 M11,4 L14,6 L13,8 L11,6", // APPAREL — shirt
  3: "M4,7 L8,3 L12,7 L12,13 L4,13 Z M6,13 L6,9 L10,9 L10,13", // HOME_GOODS — house
  4: "M5,4 L5,3 Q5,2 6,2 L10,2 Q11,2 11,3 L11,4 M4,4 L12,4 L11,13 L5,13 Z", // GROCERY — bag
  5: "M4,3 L12,3 L12,13 L4,13 Z M4,3 L4,13 M7,3 L7,13", // BOOKS_MEDIA — book spine
  6: "M8,3 A2,2 0 1 1 7.9,3 M5,8 L11,8 M5,8 A3,3 0 0 0 11,8 L11,12 L5,12 Z", // TOYS — spinning top
  7: "M6,2 L10,2 L10,4 L11,4 L11,13 L5,13 L5,4 L6,4 Z", // HEALTH_BEAUTY — bottle
  8: "M3,9 L4,6 L12,6 L13,9 M3,9 L13,9 L13,11 L3,11 Z M5,11 A1,1 0 1 1 4.9,11 M11,11 A1,1 0 1 1 10.9,11", // AUTOMOTIVE — car
  9: "M4,4 L12,4 L12,12 L4,12 Z M4,4 L12,12 M12,4 L4,12", // OTHER — boxed X
};

// One hue per category, same dark-categorical steps used elsewhere in
// this dashboard (station icons, Trends charts) — so a glance at the
// floor plan tells categories apart by color, not just glyph shape.
export const PACKAGE_COLORS: Record<number, string> = {
  0: "#8b93a1", // UNSPECIFIED — neutral
  1: "#3987e5", // ELECTRONICS — blue
  2: "#d95926", // APPAREL — orange
  3: "#199e70", // HOME_GOODS — green
  4: "#c98500", // GROCERY — yellow
  5: "#d55181", // BOOKS_MEDIA — magenta
  6: "#9085e9", // TOYS — violet
  7: "#e66767", // HEALTH_BEAUTY — red
  8: "#5aa3f0", // AUTOMOTIVE — light blue
  9: "#a99e85", // OTHER — tan
};
