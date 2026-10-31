import type { LapSummary } from "./types";
import { telemetryNumber, type TelemetrySample } from "./telemetry";

export function nearestIndex(values: number[], target: number) {
  if (!values.length) return 0;
  let low = 0;
  let high = values.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(values[low - 1] - target) < Math.abs(values[low] - target)) return low - 1;
  return low;
}

export function sampleAtLapDistance(
  samples: TelemetrySample[],
  lapNumber: number,
  distance: number,
): TelemetrySample | null {
  let nearest: TelemetrySample | null = null;
  let best = Number.POSITIVE_INFINITY;
  for (const sample of samples) {
    if (Number(sample.lap_number) !== lapNumber) continue;
    const sampleDistance = telemetryNumber(sample.lap_distance_m);
    if (sampleDistance == null) continue;
    const error = Math.abs(sampleDistance - distance);
    if (error < best) {
      best = error;
      nearest = sample;
    }
  }
  return nearest;
}

export function videoTimeAtDistance(options: {
  distance: number;
  distances: number[];
  referenceTime: number[];
  comparisonTime: number[];
  referenceLap: number;
  comparisonLap: number;
  currentLap: number | null;
  laps: LapSummary[];
}) {
  if (!options.distances.length) return null;
  const index = nearestIndex(options.distances, options.distance);
  const useReference = options.currentLap === options.referenceLap;
  const lapNumber = useReference ? options.referenceLap : options.comparisonLap;
  const lap = options.laps.find((item) => item.lap_number === lapNumber);
  const elapsed = useReference ? options.referenceTime[index] : options.comparisonTime[index];
  if (!lap || elapsed == null || !Number.isFinite(elapsed)) return null;
  return lap.start_seconds + elapsed;
}
