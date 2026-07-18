import { expect, test, type Page } from "@playwright/test";

const session = {
  schema_version: 1, session_id: "demo", name: "Sonoma Raceway", created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", status: "ready", duration_seconds: 120,
  chapters: [{ index: 0, filename: "GX010001.MP4", fingerprint: { path: "/media/GX010001.MP4", size_bytes: 1, modified_ns: 1, sha256: "0".repeat(64) }, creation_time: null, duration_seconds: 120, timeline_start_seconds: 0, timeline_end_seconds: 120, gap_before_seconds: 0, discontinuity: false }],
  streams: [], coordinate_origin: { latitude: 38.1, longitude: -122.4, altitude_m: 10, convention: "WGS84 + right-handed ENU meters" },
  processing_versions: { race_review: "test" }, processing_options: { generate_proxy: true }, artifacts: { proxy: "media/proxy.mp4", derived_telemetry: "telemetry/derived.parquet" }, warnings: [],
  edits: { track: { start_finish_a: null, start_finish_b: null, crossing_direction: 1, minimum_lap_seconds: 20, exclude_out_lap: true, exclude_in_lap: true }, calibration: { transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 }, confidence: .8, method: "test", overridden: false, diagnostics: {} }, corner_edits: [], display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" } },
};

async function mockApi(page: Page) {
  const rows = Array.from({ length: 121 }, (_, time) => [time, 38.1 + Math.sin(time / 10) * .001, -122.4 + Math.cos(time / 10) * .001, time, time, 25, 0.1, 0.4, time * 25, time < 60 ? 1 : 2, (time % 60) * 25, true]);
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/telemetry")) return route.fulfill({ json: { columns: ["timestamp", "latitude", "longitude", "east_smooth_m", "north_smooth_m", "speed_mps", "longitudinal_g", "lateral_g", "distance_m", "lap_number", "lap_distance_m", "valid"], rows, start_seconds: 0, end_seconds: 120 } });
    if (url.includes("/laps")) return route.fulfill({ json: [{ lap_number: 1, start_seconds: 0, end_seconds: 60, lap_time_seconds: 60, complete: true, excluded: false, maximum_speed_mps: 30 }, { lap_number: 2, start_seconds: 60, end_seconds: 120, lap_time_seconds: 59, complete: true, excluded: false, maximum_speed_mps: 31 }] });
    if (url.includes("/corners")) return route.fulfill({ json: [{ corner_id: "corner-1", name: "Turn 1", start_distance_m: 200, apex_distance_m: 250, end_distance_m: 300 }] });
    if (url.includes("/comparison")) return route.fulfill({ json: { distance_m: [0, 100, 200], reference_time_s: [0, 4, 8], comparison_time_s: [0, 4.1, 7.9], delta_s: [0, .1, -.1], reference_speed_mps: [20, 25, 30], comparison_speed_mps: [20, 24, 31] } });
    if (url.endsWith("/status")) return route.fulfill({ json: { session_id: "demo", status: "ready", stage: "complete", progress: 1, message: "ready", error: null, updated_at: "2026-01-01T00:00:00Z" } });
    if (url.includes("/media/proxy")) return route.fulfill({ status: 404 });
    if (url.endsWith("/api/sessions/demo")) return route.fulfill({ json: session });
    return route.fulfill({ json: [] });
  });
}

test("video clock review surfaces stay synchronized and usable", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");
  await expect(page.getByText("GR86 / REVIEW")).toBeVisible();
  await expect(page.getByLabel("Live telemetry")).toBeVisible();
  await expect(page.locator(".gauge").filter({ hasText: "LAP" }).locator("strong")).toHaveText("1");
  await page.locator("video").evaluate((element) => {
    Object.defineProperty(element, "currentTime", { configurable: true, value: 61 });
    element.dispatchEvent(new Event("seeking"));
  });
  await expect(page.getByLabel("Video timeline")).toHaveValue("61");
  await expect(page.locator(".gauge").filter({ hasText: "LAP" }).locator("strong")).toHaveText("2");
  await expect(page.getByRole("heading", { name: "Laps" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Telemetry" })).toBeVisible();
});

test("primary panels do not overlap the persistent player", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");
  const player = await page.locator(".player-bar").boundingBox();
  const stage = await page.locator(".video-stage").boundingBox();
  expect(player).not.toBeNull(); expect(stage).not.toBeNull();
  expect((stage?.y ?? 0) + (stage?.height ?? 0)).toBeLessThanOrEqual(player?.y ?? Number.MAX_VALUE);
});
