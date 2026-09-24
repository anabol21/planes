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

export interface KmlPolygonRing {
  name: string | null;
  ring: number[][];
  height_m: number | null;
  extended_data: Record<string, string>;
}

export interface LonLatBounds {
  west: number;
  south: number;
  east: number;
  north: number;
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

function elementsNamed(root: Document | Element, name: string): Element[] {
  return Array.from(root.getElementsByTagName("*")).filter(
    (element) => element.nodeType === 1 && localName(element) === name,
  );
}

function nearestAncestor(element: Element, name: string): Element | null {
  let parent = element.parentNode;
  while (parent && parent.nodeType === 1) {
    const candidate = parent as Element;
    if (localName(candidate) === name) return candidate;
    parent = candidate.parentNode;
  }
  return null;
}

function parseCoordinateTuples(text: string | null): Array<{ lon: number; lat: number; alt: number | null }> {
  const normalized = normalizedText(text);
  if (!normalized) return [];
  const tuples = [];
  for (const token of normalized.split(/\s+/)) {
    const parts = token.split(",");
    const lon = Number(parts[0]);
    const lat = Number(parts[1]);
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    let alt: number | null = null;
    if (parts.length >= 3 && parts[2]?.trim() !== "") {
      const value = Number(parts[2]);
      if (Number.isFinite(value)) alt = value;
    }
    tuples.push({ lon, lat, alt });
  }
  return tuples;
}

function loadKmlDocument(text: string, parser: XmlParser): Document {
  if (!text.trim()) throw new Error("KML file is empty.");
  const document = parser.parseFromString(text, "application/xml");
  if (document.getElementsByTagName("parsererror").length > 0) {
    throw new Error("KML contains malformed XML.");
  }
  const root = document.documentElement;
  if (!root || localName(root).toLowerCase() !== "kml") {
    throw new Error("The selected file is not a KML document.");
  }
  return document;
}

function readExtendedData(placemark: Element): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const element of elementsNamed(placemark, "Data")) {
    if (nearestAncestor(element, "Placemark") !== placemark) continue;
    const key = element.getAttribute("name")?.trim();
    if (!key) continue;
    const valueElement = elementsNamed(element, "value").find(
      (child) => nearestAncestor(child, "Data") === element,
    );
    const value = normalizedText(valueElement?.textContent ?? element.textContent);
    if (value) fields[key] = value;
  }
  for (const element of elementsNamed(placemark, "SimpleData")) {
    if (nearestAncestor(element, "Placemark") !== placemark) continue;
    const key = element.getAttribute("name")?.trim();
    const value = normalizedText(element.textContent);
    if (key && value && !(key in fields)) fields[key] = value;
  }
  return fields;
}

function outerRing(polygon: Element): { ring: number[][]; height_m: number | null } | null {
  const outer = elementsNamed(polygon, "outerBoundaryIs").find(
    (element) => nearestAncestor(element, "Polygon") === polygon,
  );
  if (!outer) return null;
  const coordinates = elementsNamed(outer, "coordinates").find(
    (element) => nearestAncestor(element, "Polygon") === polygon,
  );
  if (!coordinates) return null;
  const points = parseCoordinateTuples(coordinates.textContent);
  if (points.length < 3) return null;
  const altitudes = points.flatMap((point) => (point.alt === null ? [] : [point.alt]));
  return {
    ring: points.map((point) => [point.lon, point.lat]),
    height_m: altitudes.length ? Math.max(...altitudes) : null,
  };
}

export function extractKmlPolygons(text: string, parser: XmlParser = defaultParser()): KmlPolygonRing[] {
  const document = loadKmlDocument(text, parser);
  const polygons: KmlPolygonRing[] = [];
  for (const placemark of elementsNamed(document, "Placemark")) {
    const name = firstDirectText(placemark, "name");
    const extendedData = readExtendedData(placemark);
    for (const polygon of elementsNamed(placemark, "Polygon")) {
      if (nearestAncestor(polygon, "Placemark") !== placemark) continue;
      const ring = outerRing(polygon);
      if (!ring) continue;
      polygons.push({
        name,
        ring: ring.ring,
        height_m: ring.height_m,
        extended_data: extendedData,
      });
    }
  }
  return polygons;
}

function cross(ax: number, ay: number, bx: number, by: number): number {
  return ax * by - ay * bx;
}

function onSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): boolean {
  return (
    Math.min(ax, bx) <= px &&
    px <= Math.max(ax, bx) &&
    Math.min(ay, by) <= py &&
    py <= Math.max(ay, by)
  );
}

function segmentsIntersect(
  ax: number,
  ay: number,
  bx: number,
  by: number,
  cx: number,
  cy: number,
  dx: number,
  dy: number,
): boolean {
  const d1 = cross(cx - ax, cy - ay, bx - ax, by - ay);
  const d2 = cross(dx - ax, dy - ay, bx - ax, by - ay);
  const d3 = cross(ax - cx, ay - cy, dx - cx, dy - cy);
  const d4 = cross(bx - cx, by - cy, dx - cx, dy - cy);
  if (((d1 > 0 && d2 < 0) || (d1 < 0 && d2 > 0)) && ((d3 > 0 && d4 < 0) || (d3 < 0 && d4 > 0))) {
    return true;
  }
  if (d1 === 0 && onSegment(cx, cy, ax, ay, bx, by)) return true;
  if (d2 === 0 && onSegment(dx, dy, ax, ay, bx, by)) return true;
  if (d3 === 0 && onSegment(ax, ay, cx, cy, dx, dy)) return true;
  if (d4 === 0 && onSegment(bx, by, cx, cy, dx, dy)) return true;
  return false;
}

function pointInRing(lon: number, lat: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const xi = ring[i][0];
    const yi = ring[i][1];
    const xj = ring[j][0];
    const yj = ring[j][1];
    if (yi > lat !== yj > lat) {
      const xCross = ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
      if (lon < xCross) inside = !inside;
    }
  }
  return inside;
}

export function ringBounds(ring: number[][]): LonLatBounds | null {
  let west = Number.POSITIVE_INFINITY;
  let south = Number.POSITIVE_INFINITY;
  let east = Number.NEGATIVE_INFINITY;
  let north = Number.NEGATIVE_INFINITY;
  for (const pair of ring) {
    const lon = pair[0];
    const lat = pair[1];
    if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
    west = Math.min(west, lon);
    south = Math.min(south, lat);
    east = Math.max(east, lon);
    north = Math.max(north, lat);
  }
  if (!Number.isFinite(west) || !Number.isFinite(south)) return null;
  return { west, south, east, north };
}

export function ringIntersectsBounds(ring: number[][], bounds: LonLatBounds): boolean {
  const points = ring.filter((pair) => Number.isFinite(pair[0]) && Number.isFinite(pair[1]));
  if (points.length < 3) return false;
  const insideBounds = (lon: number, lat: number) =>
    lon >= bounds.west && lon <= bounds.east && lat >= bounds.south && lat <= bounds.north;
  if (points.some(([lon, lat]) => insideBounds(lon, lat))) return true;
  const corners = [
    [bounds.west, bounds.south],
    [bounds.east, bounds.south],
    [bounds.east, bounds.north],
    [bounds.west, bounds.north],
  ];
  for (let i = 0; i < points.length; i += 1) {
    const start = points[i];
    const end = points[(i + 1) % points.length];
    for (let j = 0; j < corners.length; j += 1) {
      const edgeStart = corners[j];
      const edgeEnd = corners[(j + 1) % corners.length];
      if (
        segmentsIntersect(
          start[0],
          start[1],
          end[0],
          end[1],
          edgeStart[0],
          edgeStart[1],
          edgeEnd[0],
          edgeEnd[1],
        )
      ) {
        return true;
      }
    }
  }
  return pointInRing(bounds.west, bounds.south, points);
}

export function parseKml(text: string, parser: XmlParser = defaultParser()): KmlSummary {
  const document = loadKmlDocument(text, parser);

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
