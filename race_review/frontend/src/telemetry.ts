import type { TelemetryWindow } from "./types";

export type TelemetrySample = Record<string, number | boolean | null>;

export function unpackTelemetry(window: TelemetryWindow): TelemetrySample[] {
  return window.rows.map((row) =>
    Object.fromEntries(window.columns.map((column, index) => [column, row[index]])),
  );
}

export function interpolateTelemetry(samples: TelemetrySample[], time: number): TelemetrySample | null {
  if (!samples.length) return null;
  let low = 0;
  let high = samples.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high + 1) / 2);
    if (Number(samples[middle].timestamp) <= time) low = middle;
    else high = middle - 1;
  }
  const first = samples[low];
  const second = samples[Math.min(low + 1, samples.length - 1)];
  const t0 = Number(first.timestamp);
  const t1 = Number(second.timestamp);
  const alpha = t1 > t0 ? Math.max(0, Math.min(1, (time - t0) / (t1 - t0))) : 0;
  const result: TelemetrySample = {};
  for (const key of Object.keys(first)) {
    const a = first[key];
    const b = second[key];
    if (typeof a === "number" && typeof b === "number" && key !== "lap_number") {
      result[key] = a + (b - a) * alpha;
    } else {
      result[key] = alpha < 0.5 ? a : b;
    }
  }
  return result;
}

export const mph = (metersPerSecond: number | null | undefined) =>
  metersPerSecond == null ? 0 : metersPerSecond * 2.2369362921;

export const feet = (meters: number | null | undefined) =>
  meters == null ? 0 : meters * 3.280839895;

export function formatTime(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes}:${(seconds % 60).toFixed(3).padStart(6, "0")}`;
}
