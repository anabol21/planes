export type KmlCategory = "survey_task" | "restricted_zones" | "obstacle";

export interface KmlBounds {
  west_lon_deg: number;
  south_lat_deg: number;
  east_lon_deg: number;
  north_lat_deg: number;
  min_altitude_m: number | null;
  max_altitude_m: number | null;
}

export interface KmlSummary {
  document_count: number;
  document_names: string[];
  document_descriptions: string[];
  placemark_count: number;
  placemark_name_samples: string[];
  placemark_description_samples: string[];
  geometry_counts: Record<string, number>;
  coordinate_tuple_count: number;
  altitude_coordinate_count: number;
  nonzero_altitude_coordinate_count: number;
  altitude_modes: Record<string, number>;
  extended_data_fields: string[];
  bounds: KmlBounds | null;
}

export interface KmlFileRecord {
  id: string;
  category: KmlCategory;
  file_name: string;
  size_bytes: number;
  status: "ready" | "error";
  summary: KmlSummary | null;
  sha256: string | null;
  raw_text: string | null;
  error: string | null;
}

export interface XmlParser {
  parseFromString(source: string, mimeType: string): Document;
}

const GEOMETRIES = new Set([
  "Point",
  "LineString",
  "LinearRing",
  "Polygon",
  "MultiGeometry",
  "Model",
  "Track",
  "MultiTrack",
]);

function localName(element: Element): string {
  return element.localName || element.tagName.split(":").at(-1) || element.tagName;
}

function normalizedText(value: string | null | undefined): string | null {
  const text = value?.replace(/\s+/g, " ").trim();
  return text ? text : null;
}

function firstDirectText(element: Element, childName: string): string | null {
  const children = Array.from(element.childNodes).filter(
    (node): node is Element => node.nodeType === 1,
  );
  for (const child of children) {
    if (localName(child) === childName) return normalizedText(child.textContent);
  }
  return null;
}

function increment(counts: Record<string, number>, key: string): void {
  counts[key] = (counts[key] ?? 0) + 1;
}

function uniqueLimited(values: string[], limit = 8): string[] {
  return [...new Set(values)].slice(0, limit);
}

function defaultParser(): XmlParser {
  if (typeof DOMParser === "undefined") {
    throw new Error("XML parser is unavailable in this environment.");
  }
  return new DOMParser();
}

export function parseKml(text: string, parser: XmlParser = defaultParser()): KmlSummary {
  if (!text.trim()) throw new Error("KML file is empty.");

  const document = parser.parseFromString(text, "application/xml");
  if (document.getElementsByTagName("parsererror").length > 0) {
    throw new Error("KML contains malformed XML.");
  }
  const root = document.documentElement;
  if (!root || localName(root).toLowerCase() !== "kml") {
    throw new Error("The selected file is not a KML document.");
  }

  const documentNames: string[] = [];
  const documentDescriptions: string[] = [];
  const placemarkNames: string[] = [];
  const placemarkDescriptions: string[] = [];
  const geometryCounts: Record<string, number> = {};
  const altitudeModes: Record<string, number> = {};
  const extendedFields: string[] = [];
  let placemarkCount = 0;
  let documentCount = 0;
  let coordinateTupleCount = 0;
  let altitudeCoordinateCount = 0;
  let nonzeroAltitudeCoordinateCount = 0;
  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;
  let minAltitude = Number.POSITIVE_INFINITY;
  let maxAltitude = Number.NEGATIVE_INFINITY;

  for (const element of Array.from(document.getElementsByTagName("*"))) {
    const name = localName(element);
    if (name === "Document") {
      documentCount += 1;
      const documentName = firstDirectText(element, "name");
      const description = firstDirectText(element, "description");
      if (documentName) documentNames.push(documentName);
      if (description) documentDescriptions.push(description);
    } else if (name === "Placemark") {
      placemarkCount += 1;
      const placemarkName = firstDirectText(element, "name");
      const description = firstDirectText(element, "description");
      if (placemarkName) placemarkNames.push(placemarkName);
      if (description) placemarkDescriptions.push(description);
    }

    if (GEOMETRIES.has(name)) increment(geometryCounts, name);
    if (name === "altitudeMode") {
      const mode = normalizedText(element.textContent);
      if (mode) increment(altitudeModes, mode);
    }
    if (name === "Data" || name === "SimpleData") {
      const fieldName = element.getAttribute("name")?.trim();
      if (fieldName) extendedFields.push(fieldName);
    }
    if (name !== "coordinates") continue;

    const coordinateText = normalizedText(element.textContent);
    if (!coordinateText) continue;
    for (const token of coordinateText.split(/\s+/)) {
      const parts = token.split(",");
      const lon = Number(parts[0]);
      const lat = Number(parts[1]);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      coordinateTupleCount += 1;
      west = Math.min(west, lon);
      east = Math.max(east, lon);
      south = Math.min(south, lat);
      north = Math.max(north, lat);
      if (parts.length < 3 || parts[2]?.trim() === "") continue;
      const altitude = Number(parts[2]);
      if (!Number.isFinite(altitude)) continue;
      altitudeCoordinateCount += 1;
      if (altitude !== 0) nonzeroAltitudeCoordinateCount += 1;
      minAltitude = Math.min(minAltitude, altitude);
      maxAltitude = Math.max(maxAltitude, altitude);
    }
  }

  return {
    document_count: documentCount,
    document_names: uniqueLimited(documentNames),
    document_descriptions: uniqueLimited(documentDescriptions),
    placemark_count: placemarkCount,
    placemark_name_samples: uniqueLimited(placemarkNames),
    placemark_description_samples: uniqueLimited(placemarkDescriptions),
    geometry_counts: geometryCounts,
    coordinate_tuple_count: coordinateTupleCount,
    altitude_coordinate_count: altitudeCoordinateCount,
    nonzero_altitude_coordinate_count: nonzeroAltitudeCoordinateCount,
    altitude_modes: altitudeModes,
    extended_data_fields: uniqueLimited(extendedFields, 20),
    bounds: coordinateTupleCount
      ? {
          west_lon_deg: west,
          south_lat_deg: south,
          east_lon_deg: east,
          north_lat_deg: north,
          min_altitude_m: altitudeCoordinateCount ? minAltitude : null,
          max_altitude_m: altitudeCoordinateCount ? maxAltitude : null,
        }
      : null,
  };
}

async function sha256(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

export async function readKmlFile(
  file: File,
  category: KmlCategory,
  id: string,
): Promise<KmlFileRecord> {
  const base = {
    id,
    category,
    file_name: file.name,
    size_bytes: file.size,
  };
  if (!file.name.toLowerCase().endsWith(".kml")) {
    return { ...base, status: "error", summary: null, sha256: null, raw_text: null, error: "Поддерживаются только файлы .kml." };
  }
  try {
    const text = await file.text();
    const summary = parseKml(text);
    return { ...base, status: "ready", summary, sha256: await sha256(text), raw_text: text, error: null };
  } catch (error) {
    return {
      ...base,
      status: "error",
      summary: null,
      sha256: null,
      raw_text: null,
      error: error instanceof Error ? error.message : "Не удалось прочитать KML.",
    };
  }
}

export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} Б`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} КБ`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} МБ`;
}
