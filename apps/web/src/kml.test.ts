import { DOMParser } from "@xmldom/xmldom";
import { describe, expect, it } from "vitest";

import { extractKmlPolygons, parseKml, ringIntersectsBounds, type XmlParser } from "./kml";

function parser(): XmlParser {
  const errors: string[] = [];
  const xmlParser = new DOMParser({
    onError(level, message) {
      if (level !== "warning") errors.push(message);
    },
  });
  return {
    parseFromString(source, mimeType) {
      errors.length = 0;
      let document;
      try {
        document = xmlParser.parseFromString(source, mimeType);
      } catch {
        throw new Error("KML contains malformed XML.");
      }
      if (errors.length) throw new Error("KML contains malformed XML.");
      return document as unknown as Document;
    },
  };
}

const VALID_KML = `<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Границы полётов</name>
    <description>Тестовое задание на съёмку</description>
    <Placemark>
      <name>Участок 1</name>
      <Polygon><outerBoundaryIs><LinearRing><coordinates>
        30.1,59.1,0 30.2,59.1,120 30.2,59.2,120 30.1,59.1,0
      </coordinates></LinearRing></outerBoundaryIs></Polygon>
    </Placemark>
  </Document>
</kml>`;

describe("KML structural parsing", () => {
  it("accepts valid KML and reports documents, placemarks, and geometry", () => {
    const summary = parseKml(VALID_KML, parser());
    expect(summary.document_count).toBe(1);
    expect(summary.document_names).toEqual(["Границы полётов"]);
    expect(summary.placemark_count).toBe(1);
    expect(summary.geometry_counts).toMatchObject({ Polygon: 1, LinearRing: 1 });
    expect(summary.coordinate_tuple_count).toBe(4);
  });

  it("reports altitude-bearing coordinates without claiming geometry validity", () => {
    const summary = parseKml(VALID_KML, parser());
    expect(summary.altitude_coordinate_count).toBe(4);
    expect(summary.nonzero_altitude_coordinate_count).toBe(2);
    expect(summary.bounds).toMatchObject({ min_altitude_m: 0, max_altitude_m: 120 });
  });

  it("rejects malformed XML", () => {
    expect(() => parseKml("<kml><Placemark></kml>", parser())).toThrow(
      "KML contains malformed XML.",
    );
  });

  it("rejects a well-formed non-KML document", () => {
    expect(() => parseKml("<scenario><name>demo</name></scenario>", parser())).toThrow(
      "The selected file is not a KML document.",
    );
  });

  it("extracts outer rings, restriction text, and obstacle height", () => {
    const polygons = extractKmlPolygons(
      `<?xml version="1.0" encoding="UTF-8"?>
      <kml xmlns="http://www.opengis.net/kml/2.2">
        <Document>
          <Placemark>
            <name>ignored placemark name</name>
            <ExtendedData>
              <Data name="Name"><value>Сектор А</value></Data>
              <Data name="Type"><value>врем_ограничение</value></Data>
              <Data name="Altitudes"><value>от 800 м AMSL до FL90</value></Data>
            </ExtendedData>
            <Polygon><outerBoundaryIs><LinearRing><coordinates>
              37.60,55.74,0 37.61,55.74,0 37.61,55.75,0 37.60,55.74,0
            </coordinates></LinearRing></outerBoundaryIs></Polygon>
          </Placemark>
          <Placemark>
            <name>BUILDING</name>
            <Polygon>
              <extrude>1</extrude>
              <altitudeMode>relativeToGround</altitudeMode>
              <outerBoundaryIs><LinearRing><coordinates>
                37.602,55.749,48 37.603,55.749,48 37.603,55.750,48 37.602,55.749,48
              </coordinates></LinearRing></outerBoundaryIs>
            </Polygon>
          </Placemark>
        </Document>
      </kml>`,
      parser(),
    );
    expect(polygons).toHaveLength(2);
    expect(polygons[0]).toMatchObject({
      name: "ignored placemark name",
      extended_data: {
        Name: "Сектор А",
        Type: "врем_ограничение",
        Altitudes: "от 800 м AMSL до FL90",
      },
    });
    expect(polygons[0].ring[0]).toEqual([37.6, 55.74]);
    expect(polygons[1]).toMatchObject({ name: "BUILDING", height_m: 48 });
    expect(
      ringIntersectsBounds(polygons[1].ring, {
        west: 37.601,
        south: 55.748,
        east: 37.609,
        north: 55.7525,
      }),
    ).toBe(true);
  });
});
