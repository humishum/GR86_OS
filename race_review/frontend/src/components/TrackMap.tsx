import { useEffect, useRef } from "react";
import maplibregl, { type GeoJSONSource, type Map as MapLibreMap, type StyleSpecification } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { TelemetrySample } from "../telemetry";
import type { CornerSummary, TrackConfig } from "../types";

type Props = { samples: TelemetrySample[]; current: TelemetrySample | null; corners: CornerSummary[]; track: TrackConfig };

export function TrackMap({ samples, current, corners, track }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);

  useEffect(() => {
    if (!container.current || mapRef.current) return;
    const routeSamples = samples
      .filter((sample) => typeof sample.longitude === "number" && typeof sample.latitude === "number" && sample.valid)
    const coordinates = routeSamples.map((sample) => [Number(sample.longitude), Number(sample.latitude)]);
    if (!coordinates.length) return;
    const grouped = new Map<number, number[][]>();
    for (const sample of routeSamples) {
      const lap = Number(sample.lap_number ?? 0);
      grouped.set(lap, [...(grouped.get(lap) ?? []), [Number(sample.longitude), Number(sample.latitude)]]);
    }
    const routeData = { type: "FeatureCollection" as const, features: [...grouped].filter(([, values]) => values.length > 1).map(([lap, values]) => ({ type: "Feature" as const, properties: { lap }, geometry: { type: "LineString" as const, coordinates: values } })) };
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
    };
    const layers: StyleSpecification["layers"] = [
        { id: "background", type: "background" as const, paint: { "background-color": "#11171a" } },
        { id: "route-shadow", type: "line" as const, source: "route", paint: { "line-color": "#000", "line-width": 8, "line-opacity": 0.6 } },
        { id: "route", type: "line" as const, source: "route", paint: { "line-color": ["match", ["get", "lap"], 1, "#ff5038", 2, "#35b7c8", 3, "#ffb238", "#869095"], "line-width": 4, "line-opacity": .8 } },
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
    const map = new maplibregl.Map({ container: container.current, style, attributionControl: false });
    const bounds = coordinates.reduce(
      (box, coordinate) => box.extend(coordinate as [number, number]),
      new maplibregl.LngLatBounds(coordinates[0] as [number, number], coordinates[0] as [number, number]),
    );
    map.once("load", () => map.fitBounds(bounds, { padding: 34, duration: 0 }));
    mapRef.current = map;
    return () => { mapRef.current = null; map.remove(); };
  }, [samples, corners, track]);

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
    };
    if (map.isStyleLoaded()) updatePosition();
    else map.once("load", updatePosition);
    return () => { map.off("load", updatePosition); };
  }, [current]);

  return <div className="track-map" ref={container} aria-label="Offline route map" />;
}
