import { expect, test, type Page } from "@playwright/test";

const session = {
  schema_version: 1, session_id: "shortcuts", name: "Keyboard Test", created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", status: "ready", duration_seconds: 120,
  chapters: [{ index: 0, filename: "test.mp4", fingerprint: { path: "/media/test.mp4", size_bytes: 1, modified_ns: 1, sha256: "0".repeat(64) }, creation_time: null, duration_seconds: 120, timeline_start_seconds: 0, timeline_end_seconds: 120, gap_before_seconds: 0, discontinuity: false }],
  streams: [], coordinate_origin: { latitude: 38.1, longitude: -122.4, altitude_m: 10, convention: "WGS84 + right-handed ENU meters" },
  processing_versions: { race_review: "test" }, processing_options: { generate_proxy: true }, artifacts: { proxy: "media/proxy.mp4", derived_telemetry: "telemetry/derived.parquet" }, warnings: [],
  edits: { track: { start_finish_a: null, start_finish_b: null, crossing_direction: 1, minimum_lap_seconds: 20, exclude_out_lap: true, exclude_in_lap: true }, calibration: { transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 }, confidence: .8, method: "test", overridden: false, diagnostics: {} }, corner_edits: [], display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" } },
};

async function mockReview(page: Page) {
  const rows = Array.from({ length: 121 }, (_, time) => [time, 38.1, -122.4, time, time, 25, 0.1, 0.4, time * 25, time < 60 ? 1 : 2, (time % 60) * 25, true]);
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/telemetry")) return route.fulfill({ json: { columns: ["timestamp", "latitude", "longitude", "east_smooth_m", "north_smooth_m", "speed_mps", "longitudinal_g", "lateral_g", "distance_m", "lap_number", "lap_distance_m", "valid"], rows, start_seconds: 0, end_seconds: 120 } });
    if (url.includes("/laps")) return route.fulfill({ json: [
      { lap_number: 1, start_seconds: 0, end_seconds: 60, lap_time_seconds: 60, complete: true, excluded: false, maximum_speed_mps: 30 },
      { lap_number: 2, start_seconds: 60, end_seconds: 120, lap_time_seconds: 60, complete: true, excluded: false, maximum_speed_mps: 31 },
    ] });
    if (url.includes("/corners")) return route.fulfill({ json: [] });
    if (url.includes("/comparison")) return route.fulfill({ json: { distance_m: [], reference_time_s: [], comparison_time_s: [], delta_s: [], reference_speed_mps: [], comparison_speed_mps: [] } });
    if (url.includes("/media/proxy")) return route.fulfill({ status: 404 });
    if (url.endsWith("/api/sessions/shortcuts")) return route.fulfill({ json: session });
    return route.fulfill({ json: [] });
  });

  await page.goto("/?session=shortcuts");
  await expect(page.getByText("GR86 / REVIEW")).toBeVisible();
  await page.locator("video").evaluate((element) => {
    let currentTime = 30;
    let paused = true;
    Object.defineProperties(element, {
      currentTime: {
        configurable: true,
        get: () => currentTime,
        set: (value: number) => {
          currentTime = value;
          element.dispatchEvent(new Event("seeking"));
        },
      },
      paused: { configurable: true, get: () => paused },
    });
    Object.defineProperty(element, "play", { configurable: true, value: () => {
      paused = false;
      element.dataset.playCalls = String(Number(element.dataset.playCalls ?? 0) + 1);
      return Promise.resolve();
    } });
    Object.defineProperty(element, "pause", { configurable: true, value: () => {
      paused = true;
      element.dataset.pauseCalls = String(Number(element.dataset.pauseCalls ?? 0) + 1);
    } });
    element.dispatchEvent(new Event("seeking"));
  });
}

test("global playback shortcuts control the canonical video clock", async ({ page }) => {
  await mockReview(page);
  const video = page.locator("video");
  const currentTime = () => video.evaluate((element) => element.currentTime);

  await page.keyboard.press("Space");
  await expect(video).toHaveAttribute("data-play-calls", "1");
  await page.keyboard.press("Space");
  await expect(video).toHaveAttribute("data-pause-calls", "1");

  await page.keyboard.press("ArrowRight");
  expect(await currentTime()).toBe(35);
  await page.keyboard.press("ArrowLeft");
  expect(await currentTime()).toBe(30);

  await page.keyboard.press("Shift+ArrowRight");
  expect(await currentTime()).toBe(60);
  await video.evaluate((element) => { element.currentTime = 65; });
  await page.keyboard.press("Shift+ArrowLeft");
  expect(await currentTime()).toBe(60);

  await video.evaluate((element) => { element.currentTime = 10; });
  await page.keyboard.press("Comma");
  expect(await currentTime()).toBeCloseTo(10 - 1001 / 60000, 6);
  await page.keyboard.press("Period");
  expect(await currentTime()).toBeCloseTo(10, 6);

  await page.keyboard.press("Shift+Period");
  await expect(page.getByLabel("Playback speed")).toHaveValue("1.5");
  expect(await video.evaluate((element) => element.playbackRate)).toBe(1.5);
  await page.keyboard.press("Shift+Comma");
  await expect(page.getByLabel("Playback speed")).toHaveValue("1");
});

test("focused player controls retain their native keyboard behavior", async ({ page }) => {
  await mockReview(page);
  const video = page.locator("video");
  const timeline = page.getByLabel("Video timeline");
  await timeline.focus();
  await page.keyboard.press("ArrowRight");
  expect(await video.evaluate((element) => element.currentTime)).toBeLessThan(31);

  await page.getByLabel("Playback speed").focus();
  await page.keyboard.press("Space");
  await expect(video).not.toHaveAttribute("data-play-calls", "1");
});
