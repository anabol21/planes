import type {
  MissionConstraintPolygon,
  MissionObstacle,
  MissionPlan,
  MissionRoute,
  PolygonGeometry,
} from "./types";

export type MapPosition = [longitude: number, latitude: number];
export type MapBounds = [southWest: MapPosition, northEast: MapPosition];

export interface RouteFeatureProperties {
  kind: "route";
  uav_id: string;
  flight_index: number;
  vpp_id: string;
  color: string;
}

export interface PolygonFeatureProperties {
  kind: "area" | "obstacle" | "constraint";
  id: string;
  name: string;
  height_m?: number;
  type?: string | null;
  altitudes_text?: string | null;
}

interface LineStringGeometry {
  type: "LineString";
  coordinates: MapPosition[];
}

interface PolygonMapGeometry {
  type: "Polygon";
  coordinates: MapPosition[][];
}

export interface MapFeature<Geometry, Properties> {
  type: "Feature";
  geometry: Geometry;
  properties: Properties;
}

export interface MapFeatureCollection<Geometry, Properties> {
  type: "FeatureCollection";
  features: Array<MapFeature<Geometry, Properties>>;
}

export interface MissionMapData {
  routes: MapFeatureCollection<LineStringGeometry, RouteFeatureProperties>;
  areas: MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties>;
  obstacles: MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties>;
  constraints: MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties>;
  colorsByUav: ReadonlyMap<string, string>;
  bounds: MapBounds | null;
  bases: BasePoint[];
}

export interface BasePoint {
  longitude: number;
  latitude: number;
  vpp_id: string;
  uav_ids: string[];
}

const ROUTE_COLORS = [
  "#22d3ee",
  "#f97316",
  "#a78bfa",
  "#4ade80",
  "#facc15",
  "#fb7185",
  "#60a5fa",
  "#2dd4bf",
  "#e879f9",
  "#f87171",
];

function isPosition(value: unknown): value is MapPosition {
  return (
    Array.isArray(value) &&
    value.length >= 2 &&
    typeof value[0] === "number" &&
    Number.isFinite(value[0]) &&
    typeof value[1] === "number" &&
    Number.isFinite(value[1])
  );
}

function polygonCoordinates(geometry: PolygonGeometry): MapPosition[][] | null {
  if (geometry.type !== "Polygon" || !Array.isArray(geometry.coordinates)) return null;
  const rings: MapPosition[][] = [];
  for (const ring of geometry.coordinates) {
    if (!Array.isArray(ring) || ring.length < 4 || !ring.every(isPosition)) return null;
    rings.push(ring.map((position) => [position[0], position[1]]));
  }
  return rings.length ? rings : null;
}

function constraintCoordinates(item: MissionConstraintPolygon): MapPosition[][] | null {
  if (!Array.isArray(item.ring) || item.ring.length < 4 || !item.ring.every(isPosition)) {
    return null;
  }
  const first = item.ring[0];
  const last = item.ring[item.ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) return null;
  return [item.ring.map((position) => [position[0], position[1]])];
}

function coordinatePairs(ring: unknown): MapPosition[] | null {
  if (!Array.isArray(ring)) return null;
  const pairs: MapPosition[] = [];
  for (const point of ring) {
    if (!isPosition(point)) return null;
    pairs.push([point[0], point[1]]);
  }
  return pairs;
}

function ringsEqual(left: MapPosition[], right: MapPosition[]): boolean {
  if (left.length !== right.length) return false;
  return left.every(
    (position, index) => position[0] === right[index][0] && position[1] === right[index][1],
  );
}

function obstacleRepeatsConstraintRing(item: MissionObstacle, plan: MissionPlan): boolean {
  if (item.polygon?.type !== "Polygon") return false;
  const outer = coordinatePairs(item.polygon.coordinates?.[0]);
  if (!outer) return false;
  return (plan.constraint_polygons ?? []).some((constraint) => {
    const ring = coordinatePairs(constraint.ring);
    return ring !== null && ringsEqual(outer, ring);
  });
}

export function colorsForRoutes(routes: MissionRoute[]): ReadonlyMap<string, string> {
  const ids = [...new Set(routes.map((route) => route.uav_id))].sort((a, b) =>
    a.localeCompare(b, "ru"),
  );
  return new Map(ids.map((id, index) => [
    id,
    ROUTE_COLORS[index] ?? `hsl(${Math.round((index * 137.508) % 360)} 78% 58%)`,
  ]));
}

function samePosition(left: MapPosition, right: MapPosition): boolean {
  return left[0] === right[0] && left[1] === right[1];
}

function surveyRings(plan: MissionPlan): MapPosition[][] {
  const rings: MapPosition[][] = [];
  for (const area of plan.areas ?? []) {
    const coordinates = polygonCoordinates(area.polygon);
    if (coordinates?.[0] && coordinates[0].length >= 4) rings.push(coordinates[0]);
  }
  return rings;
}

function onSegment(start: MapPosition, end: MapPosition, point: MapPosition): boolean {
  const cross =
    (point[0] - start[0]) * (end[1] - start[1]) -
    (point[1] - start[1]) * (end[0] - start[0]);
  if (Math.abs(cross) > 1e-10) return false;
  const dot =
    (point[0] - start[0]) * (end[0] - start[0]) +
    (point[1] - start[1]) * (end[1] - start[1]);
  if (dot < -1e-10) return false;
  const lengthSquared =
    (end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2;
  return dot <= lengthSquared + 1e-10;
}

function pointInRing(point: MapPosition, ring: MapPosition[]): boolean {
  const edges: Array<[MapPosition, MapPosition]> = [];
  for (let index = 0; index < ring.length - 1; index += 1) {
    edges.push([ring[index], ring[index + 1]]);
  }
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (!samePosition(first, last)) edges.push([last, first]);
  if (edges.some(([start, end]) => onSegment(start, end, point))) return true;
  const vertices = samePosition(first, last) ? ring.slice(0, -1) : ring;
  let inside = false;
  for (let index = 0, previous = vertices.length - 1; index < vertices.length; previous = index, index += 1) {
    const [xi, yi] = vertices[index];
    const [xj, yj] = vertices[previous];
    const crosses = (yi > point[1]) !== (yj > point[1]);
    if (!crosses) continue;
    const x = ((xj - xi) * (point[1] - yi)) / (yj - yi) + xi;
    if (point[0] < x) inside = !inside;
  }
  return inside;
}

function pointInSurvey(point: MapPosition, rings: MapPosition[][]): boolean {
  return rings.some((ring) => pointInRing(point, ring));
}

function lerp(start: MapPosition, end: MapPosition, t: number): MapPosition {
  return [start[0] + (end[0] - start[0]) * t, start[1] + (end[1] - start[1]) * t];
}

function edgeCrossing(start: MapPosition, end: MapPosition, edgeStart: MapPosition, edgeEnd: MapPosition): number | null {
  const rx = end[0] - start[0];
  const ry = end[1] - start[1];
  const sx = edgeEnd[0] - edgeStart[0];
  const sy = edgeEnd[1] - edgeStart[1];
  const denom = rx * sy - ry * sx;
  if (Math.abs(denom) < 1e-15) return null;
  const qx = edgeStart[0] - start[0];
  const qy = edgeStart[1] - start[1];
  const t = (qx * sy - qy * sx) / denom;
  const u = (qx * ry - qy * rx) / denom;
  if (t <= 1e-9 || t >= 1 - 1e-9 || u < -1e-9 || u > 1 + 1e-9) return null;
  return t;
}

function clipSegment(start: MapPosition, end: MapPosition, rings: MapPosition[][]): MapPosition[][] {
  if (samePosition(start, end)) {
    return pointInSurvey(start, rings) ? [[start, end]] : [];
  }
  const cuts = [0, 1];
  for (const ring of rings) {
    for (let index = 0; index < ring.length - 1; index += 1) {
      const t = edgeCrossing(start, end, ring[index], ring[index + 1]);
      if (t !== null) cuts.push(t);
    }
  }
  cuts.sort((left, right) => left - right);
  const marks = cuts.filter((value, index) => index === 0 || value - cuts[index - 1] > 1e-9);
  const pieces: MapPosition[][] = [];
  let current: MapPosition[] | null = null;
  for (let index = 0; index < marks.length - 1; index += 1) {
    const from = marks[index];
    const to = marks[index + 1];
    const middle = lerp(start, end, (from + to) / 2);
    if (!pointInSurvey(middle, rings)) {
      if (current) {
        pieces.push(current);
        current = null;
      }
      continue;
    }
    const head = from === 0 ? start : lerp(start, end, from);
    const tail = to === 1 ? end : lerp(start, end, to);
    if (!current) current = [head, tail];
    else current.push(tail);
  }
  if (current) pieces.push(current);
  return pieces;
}

function clipRoute(coordinates: MapPosition[], rings: MapPosition[][]): MapPosition[][] {
  const pieces: MapPosition[][] = [];
  let current: MapPosition[] | null = null;
  const take = (piece: MapPosition[]) => {
    if (piece.length < 2) return;
    if (!current) {
      current = piece;
      return;
    }
    if (samePosition(current[current.length - 1], piece[0])) current.push(...piece.slice(1));
    else {
      pieces.push(current);
      current = piece;
    }
  };
  for (let index = 0; index < coordinates.length - 1; index += 1) {
    for (const piece of clipSegment(coordinates[index], coordinates[index + 1], rings)) take(piece);
  }
  if (current) pieces.push(current);
  return pieces;
}

export function missionPlanToGeoJson(
  plan: MissionPlan,
): MapFeatureCollection<LineStringGeometry, RouteFeatureProperties> {
  const routes = plan.routes ?? [];
  const colors = colorsForRoutes(routes);
  const rings = surveyRings(plan);
  return {
    type: "FeatureCollection",
    features: routes.flatMap((route) => {
      if (route.waypoints.length < 2 || rings.length === 0) return [];
      const coordinates: MapPosition[] = route.waypoints.map((waypoint) => [
        waypoint.lon,
        waypoint.lat,
      ]);
      if (!coordinates.every(isPosition)) return [];
      return clipRoute(coordinates, rings).map((piece) => ({
        type: "Feature" as const,
        properties: {
          kind: "route" as const,
          uav_id: route.uav_id,
          flight_index: route.flight_index,
          vpp_id: route.vpp_id,
          color: colors.get(route.uav_id) ?? ROUTE_COLORS[0],
        },
        geometry: { type: "LineString" as const, coordinates: piece },
      }));
    }),
  };
}

function polygonFeatureCollection(
  plan: MissionPlan,
  kind: "area" | "obstacle",
): MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties> {
  const items = kind === "area"
    ? plan.areas ?? []
    : (plan.obstacles ?? []).filter((item) => !obstacleRepeatsConstraintRing(item, plan));
  return {
    type: "FeatureCollection",
    features: items.flatMap((item) => {
      const coordinates = polygonCoordinates(item.polygon);
      if (!coordinates) return [];
      return [{
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates },
        properties: {
          kind,
          id: item.id,
          name: item.name ?? item.id,
          ...(kind === "obstacle" && "height_m" in item && typeof item.height_m === "number"
            ? { height_m: item.height_m }
            : {}),
        },
      }];
    }),
  };
}

function constraintFeatureCollection(
  plan: MissionPlan,
): MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties> {
  return {
    type: "FeatureCollection",
    features: (plan.constraint_polygons ?? []).flatMap((item, index) => {
      const coordinates = constraintCoordinates(item);
      if (!coordinates) return [];
      return [{
        type: "Feature" as const,
        geometry: { type: "Polygon" as const, coordinates },
        properties: {
          kind: "constraint" as const,
          id: `constraint-${index + 1}`,
          name: item.name ?? `Ограничение ${index + 1}`,
          type: item.type,
          altitudes_text: item.altitudes_text,
        },
      }];
    }),
  };
}

function routeBases(routes: MissionRoute[]): BasePoint[] {
  const grouped = new Map<string, BasePoint>();
  for (const route of routes) {
    const first = route.waypoints[0];
    if (!first || !Number.isFinite(first.lon) || !Number.isFinite(first.lat)) continue;
    const key = `${route.vpp_id}\u0000${first.lon}\u0000${first.lat}`;
    const existing = grouped.get(key);
    if (existing) {
      if (!existing.uav_ids.includes(route.uav_id)) existing.uav_ids.push(route.uav_id);
    } else {
      grouped.set(key, {
        longitude: first.lon,
        latitude: first.lat,
        vpp_id: route.vpp_id,
        uav_ids: [route.uav_id],
      });
    }
  }
  return [...grouped.values()];
}

function geometryBounds(plan: MissionPlan): MapBounds | null {
  const positions: MapPosition[] = [];
  for (const route of plan.routes ?? []) {
    for (const waypoint of route.waypoints) {
      if (Number.isFinite(waypoint.lon) && Number.isFinite(waypoint.lat)) {
        positions.push([waypoint.lon, waypoint.lat]);
      }
    }
  }
  for (const item of [...(plan.areas ?? []), ...(plan.obstacles ?? [])]) {
    const coordinates = polygonCoordinates(item.polygon);
    if (coordinates) positions.push(...coordinates.flat());
  }
  for (const constraint of plan.constraint_polygons ?? []) {
    const coordinates = constraintCoordinates(constraint);
    if (coordinates) positions.push(...coordinates.flat());
  }
  if (!positions.length) return null;
  const longitudes = positions.map(([longitude]) => longitude);
  const latitudes = positions.map(([, latitude]) => latitude);
  return [
    [Math.min(...longitudes), Math.min(...latitudes)],
    [Math.max(...longitudes), Math.max(...latitudes)],
  ];
}

export function buildMissionMapData(plan: MissionPlan): MissionMapData {
  const routes = plan.routes ?? [];
  return {
    routes: missionPlanToGeoJson(plan),
    areas: polygonFeatureCollection(plan, "area"),
    obstacles: polygonFeatureCollection(plan, "obstacle"),
    constraints: constraintFeatureCollection(plan),
    colorsByUav: colorsForRoutes(routes),
    bounds: geometryBounds(plan),
    bases: routeBases(routes),
  };
}
