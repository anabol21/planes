import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Map, {
  Layer,
  Marker,
  NavigationControl,
  Popup,
  Source,
  type MapLayerMouseEvent,
  type MapRef,
} from "react-map-gl/maplibre";
import { setWorkerUrl, type StyleSpecification } from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import "maplibre-gl/dist/maplibre-gl.css";

import { buildMissionMapData, type RouteFeatureProperties } from "./missionMapData";
import type { MissionPlan } from "./types";

const ROUTE_LAYER_ID = "mission-routes";

setWorkerUrl(workerUrl);

const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    satellite: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution:
        "Tiles © Esri — Source: Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    },
  },
  layers: [{ id: "satellite", type: "raster", source: "satellite" }],
};

interface RoutePopup extends RouteFeatureProperties {
  longitude: number;
  latitude: number;
}

export function MissionMap({ plan }: { plan: MissionPlan }) {
  const data = useMemo(() => buildMissionMapData(plan), [plan]);
  const mapRef = useRef<MapRef>(null);
  const [popup, setPopup] = useState<RoutePopup | null>(null);

  const fitMission = useCallback(() => {
    if (!data.bounds || !mapRef.current) return;
    mapRef.current.fitBounds(data.bounds, {
      padding: 48,
      duration: 0,
      maxZoom: 16,
    });
  }, [data.bounds]);

  useEffect(fitMission, [fitMission]);

  if (!data.routes.features.length) {
    return (
      <div className="mission-map-empty" role="status">
        Маршруты отсутствуют в результате расчёта.
      </div>
    );
  }

  function selectRoute(event: MapLayerMouseEvent) {
    const feature = event.features?.[0];
    const properties = feature?.properties as Partial<RouteFeatureProperties> | undefined;
    if (
      properties?.kind !== "route" ||
      typeof properties.uav_id !== "string" ||
      typeof properties.flight_index !== "number" ||
      typeof properties.vpp_id !== "string"
    ) {
      return;
    }
    setPopup({
      kind: "route",
      color: typeof properties.color === "string" ? properties.color : "#22d3ee",
      uav_id: properties.uav_id,
      flight_index: properties.flight_index,
      vpp_id: properties.vpp_id,
      longitude: event.lngLat.lng,
      latitude: event.lngLat.lat,
    });
  }

  return (
    <div className="mission-map-layout">
      <div className="mission-map" aria-label="Карта рассчитанных маршрутов БПЛА">
        <Map
          ref={mapRef}
          initialViewState={{ longitude: 0, latitude: 0, zoom: 1 }}
          mapStyle={SATELLITE_STYLE}
          workerUrl={workerUrl}
          attributionControl={{ compact: true }}
          interactiveLayerIds={[ROUTE_LAYER_ID]}
          onClick={selectRoute}
          onLoad={fitMission}
        >
          <NavigationControl position="top-right" showCompass={false} />

          {data.areas.features.length > 0 && (
            <Source id="mission-areas-source" type="geojson" data={data.areas}>
              <Layer id="mission-areas-fill" type="fill" paint={{ "fill-color": "#facc15", "fill-opacity": 0.15 }} />
              <Layer id="mission-areas-outline" type="line" paint={{ "line-color": "#fde047", "line-width": 2 }} />
            </Source>
          )}

          {data.obstacles.features.length > 0 && (
            <Source id="mission-obstacles-source" type="geojson" data={data.obstacles}>
              <Layer id="mission-obstacles-fill" type="fill" paint={{ "fill-color": "#ef4444", "fill-opacity": 0.28 }} />
              <Layer id="mission-obstacles-outline" type="line" paint={{ "line-color": "#f87171", "line-width": 2 }} />
            </Source>
          )}

          {data.constraints.features.length > 0 && (
            <Source id="mission-constraints-source" type="geojson" data={data.constraints}>
              <Layer id="mission-constraints-fill" type="fill" paint={{ "fill-color": "#c084fc", "fill-opacity": 0.18 }} />
              <Layer id="mission-constraints-outline" type="line" paint={{ "line-color": "#d8b4fe", "line-width": 2, "line-dasharray": [2, 2] }} />
            </Source>
          )}

          <Source id="mission-routes-source" type="geojson" data={data.routes}>
            <Layer
              id={ROUTE_LAYER_ID}
              type="line"
              paint={{
                "line-color": ["get", "color"],
                "line-width": 4,
                "line-opacity": 0.92,
              }}
              layout={{ "line-cap": "round", "line-join": "round" }}
            />
          </Source>

          {data.bases.map((base) => (
            <Marker
              key={`${base.vpp_id}-${base.longitude}-${base.latitude}`}
              longitude={base.longitude}
              latitude={base.latitude}
              anchor="center"
            >
              <span
                className="mission-base-marker"
                title={`${base.vpp_id}: ${base.uav_ids.join(", ")}`}
                aria-label={`Старт маршрута ${base.vpp_id}`}
              />
            </Marker>
          ))}

          {popup && (
            <Popup
              longitude={popup.longitude}
              latitude={popup.latitude}
              closeButton
              closeOnClick={false}
              onClose={() => setPopup(null)}
              offset={10}
            >
              <div className="route-popup">
                <strong>{popup.uav_id}</strong>
                <span>Вылет {popup.flight_index}</span>
                <span>ВПП: {popup.vpp_id}</span>
              </div>
            </Popup>
          )}
        </Map>
      </div>

      <aside className="mission-map-legend" aria-label="Легенда маршрутов">
        <h4>Маршруты БПЛА</h4>
        <ul>
          {[...data.colorsByUav.entries()].map(([uavId, color]) => (
            <li key={uavId}>
              <span className="route-color" style={{ backgroundColor: color }} aria-hidden="true" />
              {uavId}
            </li>
          ))}
        </ul>
      </aside>
    </div>
  );
}
