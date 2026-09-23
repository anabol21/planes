import { DOMParser } from "@xmldom/xmldom";
import { describe, expect, it } from "vitest";

import { parseKml, type XmlParser } from "./kml";

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
});
