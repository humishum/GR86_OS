import type { DisplayUnits } from "./types";

export const DEFAULT_DISPLAY_UNITS: DisplayUnits = {
  speed: "mph",
  acceleration: "g",
  distance: "ft",
  time: "s",
};

export function isDisplayUnits(value: unknown): value is DisplayUnits {
  if (!value || typeof value !== "object") return false;
  const units = value as Record<string, unknown>;
  return (units.speed === "mph" || units.speed === "km/h")
    && (units.acceleration === "g" || units.acceleration === "m/s²")
    && (units.distance === "ft" || units.distance === "m")
    && units.time === "s";
}

export function storedDisplayUnits(storage: Pick<Storage, "getItem"> = localStorage): DisplayUnits {
  try {
    const stored = storage.getItem("race-review-units");
    if (!stored) return DEFAULT_DISPLAY_UNITS;
    const parsed: unknown = JSON.parse(stored);
    return isDisplayUnits(parsed) ? parsed : DEFAULT_DISPLAY_UNITS;
  } catch {
    return DEFAULT_DISPLAY_UNITS;
  }
}

export function displaySpeed(metersPerSecond: number | null | undefined, units: DisplayUnits) {
  if (metersPerSecond == null || !Number.isFinite(metersPerSecond)) return null;
  return metersPerSecond * (units.speed === "mph" ? 2.2369362921 : 3.6);
}

export function displayAcceleration(gForce: number | null | undefined, units: DisplayUnits) {
  if (gForce == null || !Number.isFinite(gForce)) return null;
  return units.acceleration === "g" ? gForce : gForce * 9.80665;
}

export function displayDistance(meters: number | null | undefined, units: DisplayUnits) {
  if (meters == null || !Number.isFinite(meters)) return null;
  return units.distance === "ft" ? meters * 3.280839895 : meters;
}

export const speedUnitLabel = (units: DisplayUnits) => units.speed;
export const accelerationUnitLabel = (units: DisplayUnits) => units.acceleration;
export const distanceUnitLabel = (units: DisplayUnits) => units.distance;
