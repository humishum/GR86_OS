import { describe, expect, it } from "vitest";
import { nearestIndex, sampleAtLapDistance, videoTimeAtDistance } from "./comparison";

describe("comparison linking", () => {
  it("maps a distance cursor onto the playing lap's video time", () => {
    const time = videoTimeAtDistance({
      distance: 100,
      distances: [0, 100, 200],
      referenceTime: [0, 4, 8],
      comparisonTime: [0, 4.5, 8.2],
      referenceLap: 1,
      comparisonLap: 2,
      currentLap: 2,
      laps: [
        { lap_number: 1, start_seconds: 0, end_seconds: 60, lap_time_seconds: 60, complete: true, excluded: false },
        { lap_number: 2, start_seconds: 60, end_seconds: 120, lap_time_seconds: 60, complete: true, excluded: false },
      ],
    });
    expect(time).toBe(64.5);
  });

  it("falls back to the comparison lap when video is outside the pair", () => {
    const time = videoTimeAtDistance({
      distance: 0,
      distances: [0, 100],
      referenceTime: [0, 4],
      comparisonTime: [0, 5],
      referenceLap: 1,
      comparisonLap: 2,
      currentLap: 3,
      laps: [
        { lap_number: 1, start_seconds: 0, end_seconds: 40, lap_time_seconds: 40, complete: true, excluded: false },
        { lap_number: 2, start_seconds: 40, end_seconds: 80, lap_time_seconds: 40, complete: true, excluded: false },
      ],
    });
    expect(time).toBe(40);
  });

  it("finds the nearest sample on a lap by distance", () => {
    const sample = sampleAtLapDistance(
      [
        { lap_number: 1, lap_distance_m: 0, timestamp: 0 },
        { lap_number: 2, lap_distance_m: 50, timestamp: 12 },
        { lap_number: 2, lap_distance_m: 90, timestamp: 18 },
      ],
      2,
      80,
    );
    expect(sample?.timestamp).toBe(18);
    expect(nearestIndex([0, 10, 20], 9)).toBe(1);
  });
});
