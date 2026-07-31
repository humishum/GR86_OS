import { telemetryNumber, type TelemetrySample } from "./telemetry";

const METERS_PER_DEGREE_LATITUDE = 111_320;
const MAX_ELEVATION_POINTS = 1_200;

export type ElevationProfile = {
  samples: TelemetrySample[];
  minimumAltitudeM: number | null;
  maximumAltitudeM: number | null;
  elevationRangeM: number;
  ribbon: {
    type: "FeatureCollection";
    features: Array<{
      type: "Feature";
      properties: { elevation_m: number; elevation_ratio: number };
      geometry: { type: "Polygon"; coordinates: number[][][] };
    }>;
  };
};

export type ProjectedElevationRoute = {
  elevated: string;
  ground: string;
  connectors: Array<{ elevated: [number, number]; ground: [number, number] }>;
};

function usableRouteSamples(samples: TelemetrySample[]) {
  return samples.filter((sample) =>
    sample.valid !== false
    && telemetryNumber(sample.longitude) != null
    && telemetryNumber(sample.latitude) != null
    && (telemetryNumber(sample.up_smooth_m) != null || telemetryNumber(sample.altitude_m) != null)
  );
}

export function representativeElevationLap(samples: TelemetrySample[]) {
  const usable = usableRouteSamples(samples);
  const laps = new Map<number, TelemetrySample[]>();
  for (const sample of usable) {
    const lap = telemetryNumber(sample.lap_number);
    if (lap != null && lap > 0) laps.set(lap, [...(laps.get(lap) ?? []), sample]);
  }
  const representative = [...laps.values()].sort((a, b) => b.length - a.length)[0] ?? usable;
  if (representative.length <= MAX_ELEVATION_POINTS) return representative;
  const stride = Math.ceil(representative.length / MAX_ELEVATION_POINTS);
  const reduced = representative.filter((_, index) => index % stride === 0);
  const last = representative[representative.length - 1];
  if (reduced[reduced.length - 1] !== last) reduced.push(last);
  return reduced;
}

function routeElevation(sample: TelemetrySample, altitudeOriginM: number) {
  return telemetryNumber(sample.up_smooth_m)
    ?? ((telemetryNumber(sample.altitude_m) ?? altitudeOriginM) - altitudeOriginM);
}

function offsetCoordinate(
  longitude: number,
  latitude: number,
  eastM: number,
  northM: number,
) {
  const metersPerDegreeLongitude =
    METERS_PER_DEGREE_LATITUDE * Math.max(0.01, Math.cos(latitude * Math.PI / 180));
  return [
    longitude + eastM / metersPerDegreeLongitude,
    latitude + northM / METERS_PER_DEGREE_LATITUDE,
  ];
}

export function buildElevationProfile(samples: TelemetrySample[], halfWidthM = 2.4): ElevationProfile {
  const route = representativeElevationLap(samples);
  const altitudes = route
    .map((sample) => telemetryNumber(sample.altitude_m))
    .filter((value): value is number => value != null);
  const minimumAltitudeM = altitudes.length ? Math.min(...altitudes) : null;
  const maximumAltitudeM = altitudes.length ? Math.max(...altitudes) : null;
  const altitudeOriginM = minimumAltitudeM ?? 0;
  const elevations = route.map((sample) => routeElevation(sample, altitudeOriginM));
  const minimumElevation = elevations.length ? Math.min(...elevations) : 0;
  const maximumElevation = elevations.length ? Math.max(...elevations) : 0;
  const elevationRangeM = Math.max(0, maximumElevation - minimumElevation);
  const features: ElevationProfile["ribbon"]["features"] = [];

  for (let index = 1; index < route.length; index += 1) {
    const first = route[index - 1];
    const second = route[index];
    const firstLongitude = Number(first.longitude);
    const firstLatitude = Number(first.latitude);
    const secondLongitude = Number(second.longitude);
    const secondLatitude = Number(second.latitude);
    const meanLatitude = (firstLatitude + secondLatitude) / 2;
    const eastM = (secondLongitude - firstLongitude)
      * METERS_PER_DEGREE_LATITUDE * Math.cos(meanLatitude * Math.PI / 180);
    const northM = (secondLatitude - firstLatitude) * METERS_PER_DEGREE_LATITUDE;
    const lengthM = Math.hypot(eastM, northM);
    if (!Number.isFinite(lengthM) || lengthM < 0.05) continue;
    const normalEastM = -northM / lengthM * halfWidthM;
    const normalNorthM = eastM / lengthM * halfWidthM;
    const elevationM = ((elevations[index - 1] + elevations[index]) / 2) - minimumElevation;
    const elevationRatio = elevationRangeM > 0 ? elevationM / elevationRangeM : 0;
    const firstLeft = offsetCoordinate(
      firstLongitude, firstLatitude, normalEastM, normalNorthM,
    );
    const firstRight = offsetCoordinate(
      firstLongitude, firstLatitude, -normalEastM, -normalNorthM,
    );
    const secondLeft = offsetCoordinate(
      secondLongitude, secondLatitude, normalEastM, normalNorthM,
    );
    const secondRight = offsetCoordinate(
      secondLongitude, secondLatitude, -normalEastM, -normalNorthM,
    );
    features.push({
      type: "Feature",
      properties: { elevation_m: elevationM, elevation_ratio: elevationRatio },
      geometry: {
        type: "Polygon",
        coordinates: [[firstLeft, secondLeft, secondRight, firstRight, firstLeft]],
      },
    });
  }

  return {
    samples: route,
    minimumAltitudeM,
    maximumAltitudeM,
    elevationRangeM,
    ribbon: { type: "FeatureCollection", features },
  };
}

export function projectElevationRoute(
  samples: TelemetrySample[],
  verticalScale: number,
): ProjectedElevationRoute {
  const route = representativeElevationLap(samples);
  const bearing = -28 * Math.PI / 180;
  const cosine = Math.cos(bearing);
  const sine = Math.sin(bearing);
  const altitudeOriginM = telemetryNumber(route[0]?.altitude_m) ?? 0;
  const raw = route.flatMap((sample) => {
    const east = telemetryNumber(sample.east_smooth_m);
    const north = telemetryNumber(sample.north_smooth_m);
    if (east == null || north == null) return [];
    const x = east * cosine - north * sine;
    const depth = east * sine + north * cosine;
    const elevation = routeElevation(sample, altitudeOriginM);
    return [{
      elevated: [x, -depth * 0.55 - elevation * verticalScale] as [number, number],
      ground: [x, -depth * 0.55] as [number, number],
    }];
  });
  if (raw.length < 2) return { elevated: "", ground: "", connectors: [] };
  const all = raw.flatMap((point) => [point.elevated, point.ground]);
  const minimumX = Math.min(...all.map((point) => point[0]));
  const maximumX = Math.max(...all.map((point) => point[0]));
  const minimumY = Math.min(...all.map((point) => point[1]));
  const maximumY = Math.max(...all.map((point) => point[1]));
  const width = Math.max(1, maximumX - minimumX);
  const height = Math.max(1, maximumY - minimumY);
  const project = ([x, y]: [number, number]): [number, number] => [
    5 + (x - minimumX) / width * 90,
    5 + (y - minimumY) / height * 90,
  ];
  const projected = raw.map((point) => ({
    elevated: project(point.elevated),
    ground: project(point.ground),
  }));
  const points = (key: "elevated" | "ground") =>
    projected.map((point) => point[key].map((value) => value.toFixed(2)).join(",")).join(" ");
  const connectorStride = Math.max(1, Math.floor(projected.length / 12));
  return {
    elevated: points("elevated"),
    ground: points("ground"),
    connectors: projected.filter((_, index) => index % connectorStride === 0),
  };
}
