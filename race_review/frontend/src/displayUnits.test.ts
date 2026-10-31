import { describe, expect, it } from "vitest";
import {
  DEFAULT_DISPLAY_UNITS,
  displayAcceleration,
  displayDistance,
  displaySpeed,
  storedDisplayUnits,
} from "./displayUnits";

const metric = { speed: "km/h", acceleration: "m/s²", distance: "m", time: "s" } as const;

describe("display units", () => {
  it("converts canonical SI telemetry without changing the source values", () => {
    expect(displaySpeed(25, metric)).toBeCloseTo(90);
    expect(displayAcceleration(1, metric)).toBeCloseTo(9.80665);
    expect(displayDistance(100, metric)).toBe(100);
    expect(displaySpeed(25, DEFAULT_DISPLAY_UNITS)).toBeCloseTo(55.9234);
    expect(displayDistance(100, DEFAULT_DISPLAY_UNITS)).toBeCloseTo(328.084);
  });

  it("validates stored preferences and safely falls back", () => {
    expect(storedDisplayUnits({ getItem: () => JSON.stringify(metric) })).toEqual(metric);
    expect(storedDisplayUnits({ getItem: () => "{broken" })).toEqual(DEFAULT_DISPLAY_UNITS);
    expect(storedDisplayUnits({ getItem: () => JSON.stringify({ ...metric, speed: "knots" }) })).toEqual(DEFAULT_DISPLAY_UNITS);
  });
});
