import { describe, expect, it } from "vitest";
import { interpolateTelemetry, type TelemetrySample } from "./telemetry";

const samples: TelemetrySample[] = [
  {
    timestamp: 10,
    speed_mps: 20,
    lateral_g: null,
    lap_number: 1,
    gps_valid: false,
  },
  {
    timestamp: 12,
    speed_mps: 30,
    lateral_g: 0.8,
    lap_number: 2,
    gps_valid: true,
  },
];

describe("interpolateTelemetry", () => {
  it("returns null when there are no telemetry samples", () => {
    expect(interpolateTelemetry([], 10)).toBeNull();
  });

  it("clamps readings before and after the available telemetry range", () => {
    expect(interpolateTelemetry(samples, 4)).toEqual(samples[0]);
    expect(interpolateTelemetry(samples, 20)).toEqual(samples[1]);
  });

  it("linearly interpolates continuous values and selects discrete values", () => {
    expect(interpolateTelemetry(samples, 10.5)).toMatchObject({
      timestamp: 10.5,
      speed_mps: 22.5,
      lateral_g: null,
      lap_number: 1,
      gps_valid: false,
    });
    expect(interpolateTelemetry(samples, 11)).toMatchObject({
      timestamp: 11,
      speed_mps: 25,
      lateral_g: 0.8,
      lap_number: 2,
      gps_valid: true,
    });
  });

  it("preserves missing fields instead of interpolating them as zero", () => {
    const beforeMidpoint = interpolateTelemetry(samples, 10.9);
    expect(beforeMidpoint?.lateral_g).toBeNull();
    expect(beforeMidpoint?.lateral_g).not.toBe(0);

    const reverseMissing = [
      { timestamp: 10, longitudinal_g: -0.5 },
      { timestamp: 12, longitudinal_g: null },
    ];
    const afterMidpoint = interpolateTelemetry(reverseMissing, 11.1);
    expect(afterMidpoint?.longitudinal_g).toBeNull();
    expect(afterMidpoint?.longitudinal_g).not.toBe(0);
  });
});
