import { useEffect, useMemo, useRef, useState } from "react";
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { TelemetrySample } from "../telemetry";
import { telemetryNumber } from "../telemetry";
import { DEFAULT_DISPLAY_UNITS, displayDistance, distanceUnitLabel } from "../displayUnits";
import { buildElevationProfile, projectElevationRoute } from "../trackGeometry";
import type { CornerSummary, DisplayUnits, TrackConfig } from "../types";

type Props = { samples: TelemetrySample[]; current: TelemetrySample | null; corners: CornerSummary[]; track: TrackConfig; units?: DisplayUnits };
type LapStyle = { color: string; visible: boolean };

const LAP_COLORS = ["#ff5038", "#35b7c8", "#ffb238", "#ad7cff", "#7ed47e", "#f2f5f6"];

function lapNumbersFrom(samples: TelemetrySample[]) {
  return [...new Set(samples.map((sample) => Number(sample.lap_number)).filter((lap) => lap > 0))].sort((a, b) => a - b);
}

function routeDataFrom(samples: TelemetrySample[], styles: Record<number, LapStyle>) {
  const grouped = new Map<number, number[][]>();
  for (const sample of samples) {
    if (typeof sample.longitude !== "number" || typeof sample.latitude !== "number" || !sample.valid) continue;
    const lap = Number(sample.lap_number ?? 0);
    grouped.set(lap, [...(grouped.get(lap) ?? []), [sample.longitude, sample.latitude]]);
  }
  return {
    type: "FeatureCollection" as const,
    features: [...grouped].filter(([, values]) => values.length > 1).map(([lap, values], index) => ({
      type: "Feature" as const,
      properties: {
        lap,
        color: styles[lap]?.color ?? LAP_COLORS[index % LAP_COLORS.length],
        visible: styles[lap]?.visible === false ? 0 : 1,
      },
      geometry: { type: "LineString" as const, coordinates: values },
    })),
  };
}

function bearingBetween(first: TelemetrySample | undefined, second: TelemetrySample | null) {
  if (!first || !second || typeof first.latitude !== "number" || typeof first.longitude !== "number"
    || typeof second.latitude !== "number" || typeof second.longitude !== "number") return 0;
  const firstLatitude = first.latitude * Math.PI / 180;
  const secondLatitude = second.latitude * Math.PI / 180;
  const longitudeDelta = (second.longitude - first.longitude) * Math.PI / 180;
  const y = Math.sin(longitudeDelta) * Math.cos(secondLatitude);
  const x = Math.cos(firstLatitude) * Math.sin(secondLatitude)
    - Math.sin(firstLatitude) * Math.cos(secondLatitude) * Math.cos(longitudeDelta);
  return Math.atan2(y, x) * 180 / Math.PI;
}

export function TrackMap({ samples, current, corners, track, units = DEFAULT_DISPLAY_UNITS }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const boundsRef = useRef<maplibregl.LngLatBounds | null>(null);
  const [cameraMode, setCameraMode] = useState<"3d" | "top">("3d");
  const [verticalScale, setVerticalScale] = useState<1 | 3>(3);
  const [followMode, setFollowMode] = useState(false);
  const [headingUp, setHeadingUp] = useState(false);
  const [lapStyles, setLapStyles] = useState<Record<number, LapStyle>>({});
  const [mapError, setMapError] = useState("");
  const lapNumbers = useMemo(() => lapNumbersFrom(samples), [samples]);
  const elevation = useMemo(() => buildElevationProfile(samples), [samples]);
  const fallbackRoute = useMemo(
    () => projectElevationRoute(samples, verticalScale),
    [samples, verticalScale],
  );
  useEffect(() => {
    setLapStyles((previous) => Object.fromEntries(lapNumbers.map((lap, index) => [
      lap,
      previous[lap] ?? { color: LAP_COLORS[index % LAP_COLORS.length], visible: true },
    ])));
  }, [lapNumbers]);

  const frameRoute = (mode: "3d" | "top", animate = true) => {
    const map = mapRef.current;
    const bounds = boundsRef.current;
    if (!map || !bounds) return;
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    map.fitBounds(bounds, {
      padding: 34,
      pitch: mode === "3d" ? 58 : 0,
      bearing: mode === "3d" ? -28 : 0,
      duration: animate && !reduceMotion ? 450 : 0,
    });
    setCameraMode(mode);
  };

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const routeSamples = samples
      .filter((sample) => typeof sample.longitude === "number" && typeof sample.latitude === "number" && sample.valid)
    const coordinates = routeSamples.map((sample) => [Number(sample.longitude), Number(sample.latitude)]);
    if (!coordinates.length) return;
    const routeData = routeDataFrom(routeSamples, lapStyles);
    const nearest = (east: number, north: number) => routeSamples.reduce((best, sample) => {
      const distance = Math.hypot(Number(sample.east_smooth_m) - east, Number(sample.north_smooth_m) - north);
      return distance < best.distance ? { sample, distance } : best;
    }, { sample: routeSamples[0], distance: Number.POSITIVE_INFINITY }).sample;
    const firstCompleteLap = Math.min(...routeSamples.map((sample) => Number(sample.lap_number)).filter((lap) => lap > 0));
    const lapSamples = routeSamples.filter((sample) => Number(sample.lap_number) === firstCompleteLap);
    const cornerData = { type: "FeatureCollection" as const, features: corners.map((corner) => {
      const sample = lapSamples.reduce((best, item) => Math.abs(Number(item.lap_distance_m) - corner.apex_distance_m) < Math.abs(Number(best.lap_distance_m) - corner.apex_distance_m) ? item : best, lapSamples[0] ?? routeSamples[0]);
      return { type: "Feature" as const, properties: { name: corner.name }, geometry: { type: "Point" as const, coordinates: [Number(sample.longitude), Number(sample.latitude)] } };
    }) };
    const lineSamples = track.start_finish_a && track.start_finish_b ? [nearest(track.start_finish_a.east_m, track.start_finish_a.north_m), nearest(track.start_finish_b.east_m, track.start_finish_b.north_m)] : [];
    const lineData = lineSamples.length === 2
      ? { type: "Feature" as const, properties: {}, geometry: { type: "LineString" as const, coordinates: lineSamples.map((sample) => [Number(sample.longitude), Number(sample.latitude)]) } }
      : { type: "FeatureCollection" as const, features: [] };
    const sources: StyleSpecification["sources"] = {
        route: {
          type: "geojson" as const,
          data: routeData,
        },
        position: {
          type: "geojson" as const,
          data: { type: "Feature" as const, properties: {}, geometry: { type: "Point" as const, coordinates: coordinates[0] } },
        },
        corners: { type: "geojson", data: cornerData },
        start: { type: "geojson", data: lineData },
        elevation: { type: "geojson", data: elevation.ribbon },
    };
    const layers: StyleSpecification["layers"] = [
        { id: "background", type: "background" as const, paint: { "background-color": "#11171a" } },
        { id: "route-shadow", type: "line" as const, source: "route", paint: { "line-color": "#000", "line-width": 8, "line-opacity": ["*", 0.6, ["get", "visible"]] } },
        {
          id: "route-elevation",
          type: "fill-extrusion",
          source: "elevation",
          paint: {
            "fill-extrusion-base": 0,
            "fill-extrusion-height": ["+", 1.5, ["*", ["get", "elevation_m"], verticalScale]],
            "fill-extrusion-color": [
              "interpolate", ["linear"], ["get", "elevation_ratio"],
              0, "#35b7c8",
              0.5, "#ffb238",
              1, "#ff5038",
            ],
            "fill-extrusion-opacity": 0.92,
          },
        },
        { id: "route", type: "line" as const, source: "route", paint: { "line-color": ["get", "color"], "line-width": 3, "line-opacity": ["*", .82, ["get", "visible"]] } },
        { id: "start", type: "line", source: "start", paint: { "line-color": "#f8f9f9", "line-width": 3 } },
        { id: "corners", type: "circle", source: "corners", paint: { "circle-color": "#ffb238", "circle-radius": 4, "circle-stroke-color": "#111", "circle-stroke-width": 1 } },
        { id: "position", type: "circle" as const, source: "position", paint: { "circle-color": "#ff5038", "circle-radius": 7, "circle-stroke-color": "#fff", "circle-stroke-width": 2 } },
    ];
    const tileUrl = localStorage.getItem("race-review-map-tiles");
    if (tileUrl) {
      sources.tiles = { type: "raster", tiles: [tileUrl], tileSize: 256 };
      layers.splice(1, 0, { id: "tiles", type: "raster", source: "tiles", paint: { "raster-opacity": .55 } });
    }
    const style: StyleSpecification = {
      version: 8,
      sources,
      layers,
    };
    container.current.setAttribute("data-position-longitude", String(coordinates[0][0]));
    container.current.setAttribute("data-position-latitude", String(coordinates[0][1]));
    let map: MapLibreMap;
    try {
      map = new maplibregl.Map({
        container: container.current,
        style,
        attributionControl: false,
      });
      setMapError("");
    } catch {
      setMapError("3D rendering is unavailable. Check browser WebGL support.");
      return;
    }
    const syncCameraAttributes = () => {
      const center = map.getCenter();
      container.current?.setAttribute("data-camera-longitude", String(center.lng));
      container.current?.setAttribute("data-camera-latitude", String(center.lat));
      container.current?.setAttribute("data-camera-pitch", String(map.getPitch()));
      container.current?.setAttribute("data-camera-bearing", String(map.getBearing()));
    };
    map.on("moveend", syncCameraAttributes);
    map.on("dragstart", () => setFollowMode(false));
    map.addControl(new maplibregl.NavigationControl({
      showCompass: true,
      showZoom: true,
      visualizePitch: true,
    }), "top-right");
    const bounds = coordinates.reduce(
      (box, coordinate) => box.extend(coordinate as [number, number]),
      new maplibregl.LngLatBounds(coordinates[0] as [number, number], coordinates[0] as [number, number]),
    );
    boundsRef.current = bounds;
    map.once("load", () => {
      frameRoute("3d", false);
      syncCameraAttributes();
    });
    mapRef.current = map;
    return () => {
      boundsRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, [samples, corners, track, elevation]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateRoutes = () => {
      const source = map.getSource("route") as GeoJSONSource | undefined;
      source?.setData(routeDataFrom(samples, lapStyles));
    };
    if (map.isStyleLoaded()) updateRoutes();
    else map.once("load", updateRoutes);
    return () => { map.off("load", updateRoutes); };
  }, [lapStyles, samples]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const elevationLap = Number(elevation.samples[0]?.lap_number ?? 0);
    const updateElevationVisibility = () => {
      if (!map.getLayer("route-elevation")) return;
      map.setPaintProperty(
        "route-elevation",
        "fill-extrusion-opacity",
        lapStyles[elevationLap]?.visible === false ? 0 : 0.92,
      );
    };
    if (map.isStyleLoaded()) updateElevationVisibility();
    else map.once("load", updateElevationVisibility);
    return () => { map.off("load", updateElevationVisibility); };
  }, [elevation.samples, lapStyles]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const updateScale = () => {
      if (!map.getLayer("route-elevation")) return;
      map.setPaintProperty(
        "route-elevation",
        "fill-extrusion-height",
        ["+", 1.5, ["*", ["get", "elevation_m"], verticalScale]],
      );
    };
    if (map.isStyleLoaded()) updateScale();
    else map.once("load", updateScale);
    return () => { map.off("load", updateScale); };
  }, [verticalScale]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !current || typeof current.longitude !== "number" || typeof current.latitude !== "number") return;
    const updatePosition = () => {
      const source = map.getSource("position") as GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: "Feature",
        properties: {},
        geometry: { type: "Point", coordinates: [current.longitude as number, current.latitude as number] },
      });
      container.current?.setAttribute("data-position-longitude", String(current.longitude));
      container.current?.setAttribute("data-position-latitude", String(current.latitude));
      const altitude = telemetryNumber(current.altitude_m);
      if (altitude != null) {
        container.current?.setAttribute("data-position-altitude", String(altitude));
      }
      if (followMode) {
        const timestamp = Number(current.timestamp);
        const index = samples.reduce((best, sample, sampleIndex) =>
          Math.abs(Number(sample.timestamp) - timestamp) < Math.abs(Number(samples[best]?.timestamp) - timestamp)
            ? sampleIndex
            : best, 0);
        map.easeTo({
          center: [current.longitude as number, current.latitude as number],
          bearing: headingUp ? -bearingBetween(samples[Math.max(0, index - 1)], current) : 0,
          duration: 0,
        });
      }
    };
    if (map.isStyleLoaded()) updatePosition();
    else map.once("load", updatePosition);
    return () => { map.off("load", updatePosition); };
  }, [current, followMode, headingUp, samples]);

  const altitude = telemetryNumber(current?.altitude_m);
  return <div
    className="track-map-shell"
    data-camera-mode={cameraMode}
    data-follow-mode={followMode}
    data-heading-up={headingUp}
    data-elevation-range={elevation.elevationRangeM.toFixed(1)}
  >
    <div
      className="track-map"
      ref={container}
      aria-label="Offline route map"
      aria-describedby="track-map-help"
    />
    {mapError && fallbackRoute.elevated && <svg
      className="track-map__fallback"
      viewBox="0 0 100 100"
      preserveAspectRatio="xMidYMid meet"
      role="img"
      aria-label="Software-rendered 3D elevation route"
    >
      <defs>
        <linearGradient id="track-elevation-gradient" x1="0" y1="1" x2="1" y2="0">
          <stop offset="0" stopColor="#35b7c8" />
          <stop offset=".55" stopColor="#ffb238" />
          <stop offset="1" stopColor="#ff5038" />
        </linearGradient>
      </defs>
      <polyline className="track-map__fallback-ground" points={fallbackRoute.ground} />
      {fallbackRoute.connectors.map((connector, index) => <line
        key={index}
        className="track-map__fallback-connector"
        x1={connector.ground[0]}
        y1={connector.ground[1]}
        x2={connector.elevated[0]}
        y2={connector.elevated[1]}
      />)}
      <polyline className="track-map__fallback-route" points={fallbackRoute.elevated} />
    </svg>}
    {mapError && <div className="track-map__error" role="status">{mapError}</div>}
    <div className="track-map__controls" aria-label="Track camera controls">
      <button
        type="button"
        aria-pressed={cameraMode === "3d"}
        onClick={() => frameRoute("3d")}
      >3D</button>
      <button
        type="button"
        aria-pressed={cameraMode === "top"}
        onClick={() => frameRoute("top")}
      >TOP</button>
      <button type="button" onClick={() => { setFollowMode(false); frameRoute(cameraMode); }}>FULL ROUTE</button>
      <button
        type="button"
        aria-label="Follow current position"
        aria-pressed={followMode}
        onClick={() => setFollowMode((value) => !value)}
      >FOLLOW</button>
      <button
        type="button"
        aria-label="Heading-up map"
        aria-pressed={headingUp}
        onClick={() => {
          setHeadingUp((value) => !value);
          setFollowMode(true);
        }}
      >HEADING</button>
      <button
        type="button"
        aria-label={`Vertical exaggeration ${verticalScale}×`}
        onClick={() => setVerticalScale((value) => value === 1 ? 3 : 1)}
      >Z {verticalScale}×</button>
    </div>
    {!!lapNumbers.length && <fieldset className="track-map__laps">
      <legend>Route laps</legend>
      {lapNumbers.map((lap) => <label key={lap}>
        <input
          type="checkbox"
          aria-label={`Show lap ${lap}`}
          checked={lapStyles[lap]?.visible ?? true}
          onChange={(event) => setLapStyles((previous) => ({
            ...previous,
            [lap]: { color: previous[lap]?.color ?? LAP_COLORS[0], visible: event.target.checked },
          }))}
        />
        <input
          type="color"
          aria-label={`Lap ${lap} color`}
          value={lapStyles[lap]?.color ?? LAP_COLORS[0]}
          onChange={(event) => setLapStyles((previous) => ({
            ...previous,
            [lap]: { color: event.target.value, visible: previous[lap]?.visible ?? true },
          }))}
        />
        <span>L{lap}</span>
      </label>)}
    </fieldset>}
    <div className="track-map__elevation" aria-label="Track elevation">
      <span>ALT {altitude == null ? "—" : `${displayDistance(altitude, units)?.toFixed(1)} ${distanceUnitLabel(units)}`}</span>
      <span>
        RANGE {elevation.minimumAltitudeM == null || elevation.maximumAltitudeM == null
          ? "—"
          : `${displayDistance(elevation.minimumAltitudeM, units)?.toFixed(0)}–${displayDistance(elevation.maximumAltitudeM, units)?.toFixed(0)} ${distanceUnitLabel(units)}`}
      </span>
    </div>
    <p className="visually-hidden" id="track-map-help">
      Drag to pan. Hold Shift or use the compass control while dragging to rotate and tilt.
      Follow keeps the current chart or video position centered. Heading-up rotates the
      route in the direction of travel. Route height represents GoPro GPS altitude.
    </p>
  </div>;
}
