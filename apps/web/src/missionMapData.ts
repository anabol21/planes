import type {
  MissionConstraintPolygon,
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

export function colorsForRoutes(routes: MissionRoute[]): ReadonlyMap<string, string> {
  const ids = [...new Set(routes.map((route) => route.uav_id))].sort((a, b) =>
    a.localeCompare(b, "ru"),
  );
  return new Map(ids.map((id, index) => [
    id,
    ROUTE_COLORS[index] ?? `hsl(${Math.round((index * 137.508) % 360)} 78% 58%)`,
  ]));
}

export function missionPlanToGeoJson(
  plan: MissionPlan,
): MapFeatureCollection<LineStringGeometry, RouteFeatureProperties> {
  const routes = plan.routes ?? [];
  const colors = colorsForRoutes(routes);
  return {
    type: "FeatureCollection",
    features: routes.flatMap((route) => {
      if (route.waypoints.length < 2) return [];
      const coordinates: MapPosition[] = route.waypoints.map((waypoint) => [
        waypoint.lon,
        waypoint.lat,
      ]);
      if (!coordinates.every(isPosition)) return [];
      return [{
        type: "Feature" as const,
        properties: {
          kind: "route" as const,
          uav_id: route.uav_id,
          flight_index: route.flight_index,
          vpp_id: route.vpp_id,
          color: colors.get(route.uav_id) ?? ROUTE_COLORS[0],
        },
        geometry: { type: "LineString" as const, coordinates },
      }];
    }),
  };
}

function polygonFeatureCollection(
  plan: MissionPlan,
  kind: "area" | "obstacle",
): MapFeatureCollection<PolygonMapGeometry, PolygonFeatureProperties> {
  const items = kind === "area" ? plan.areas ?? [] : plan.obstacles ?? [];
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
