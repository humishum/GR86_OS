import { expect, test, type Locator, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

const mediaPath = fileURLToPath(new URL("./fixtures/sync-clock.mp4", import.meta.url));

const session = {
  schema_version: 1,
  session_id: "media-sync",
  name: "Headless Sync Circuit",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  status: "ready",
  duration_seconds: 4,
  chapters: [{
    index: 0,
    filename: "sync-clock.mp4",
    fingerprint: { path: "/fixtures/sync-clock.mp4", size_bytes: 1, modified_ns: 1, sha256: "0".repeat(64) },
    creation_time: null,
    duration_seconds: 4,
    timeline_start_seconds: 0,
    timeline_end_seconds: 4,
    gap_before_seconds: 0,
    discontinuity: false,
  }],
  streams: [],
  coordinate_origin: { latitude: 38.16, longitude: -122.46, altitude_m: 10, convention: "WGS84 + right-handed ENU meters" },
  processing_versions: { race_review: "test" },
  processing_options: { generate_proxy: true },
  artifacts: { proxy: "media/proxy.mp4", derived_telemetry: "telemetry/derived.parquet" },
  warnings: [],
  edits: {
    track: { start_finish_a: null, start_finish_b: null, crossing_direction: 1, minimum_lap_seconds: 1, exclude_out_lap: false, exclude_in_lap: false },
    calibration: { transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 }, confidence: .8, method: "test", overridden: false, diagnostics: {} },
    corner_edits: [],
    display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" },
  },
};

const telemetryRows = Array.from({ length: 9 }, (_, index) => {
  const time = index / 2;
  const lapNumber = time < 1.5 ? 1 : time < 3 ? 2 : 3;
  const speed = 5 + time * 8;
  const angle = time * 1.35;
  return [
    time,
    38.16 + Math.sin(angle) * .002,
    -122.46 + Math.cos(angle) * .002,
    Math.cos(angle) * 100,
    Math.sin(angle) * 100,
    speed,
    -.3 + time * .15,
    Math.sin(angle) * .8,
    time * speed,
    lapNumber,
    (time % 1.5) * speed,
    true,
  ];
});

async function mockReview(page: Page) {
  const media = readFileSync(mediaPath);
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/media/proxy")) {
      const range = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/);
      if (!range) return route.fulfill({ body: media, contentType: "video/mp4" });
      const start = Number(range[1]);
      const end = range[2] ? Math.min(Number(range[2]), media.length - 1) : media.length - 1;
      return route.fulfill({
        status: 206,
        body: media.subarray(start, end + 1),
        contentType: "video/mp4",
        headers: {
          "Accept-Ranges": "bytes",
          "Content-Length": String(end - start + 1),
          "Content-Range": `bytes ${start}-${end}/${media.length}`,
        },
      });
    }
    if (url.includes("/telemetry")) {
      return route.fulfill({ json: {
        columns: ["timestamp", "latitude", "longitude", "east_smooth_m", "north_smooth_m", "speed_mps", "longitudinal_g", "lateral_g", "distance_m", "lap_number", "lap_distance_m", "valid"],
        rows: telemetryRows,
        start_seconds: 0,
        end_seconds: 4,
      } });
    }
    if (url.includes("/laps")) {
      return route.fulfill({ json: [
        { lap_number: 1, start_seconds: 0, end_seconds: 1.5, lap_time_seconds: 1.5, complete: true, excluded: false, maximum_speed_mps: 17 },
        { lap_number: 2, start_seconds: 1.5, end_seconds: 3, lap_time_seconds: 1.5, complete: true, excluded: false, maximum_speed_mps: 29 },
        { lap_number: 3, start_seconds: 3, end_seconds: 4, lap_time_seconds: 1, complete: false, excluded: false, maximum_speed_mps: 37 },
      ] });
    }
    if (url.includes("/corners")) return route.fulfill({ json: [] });
    if (url.includes("/comparison")) {
      return route.fulfill({ json: {
        distance_m: [0, 10, 20],
        reference_time_s: [0, .75, 1.5],
        comparison_time_s: [0, .8, 1.5],
        delta_s: [0, .05, 0],
        reference_speed_mps: [5, 11, 17],
        comparison_speed_mps: [17, 23, 29],
      } });
    }
    if (url.endsWith("/api/sessions/media-sync")) return route.fulfill({ json: session });
    return route.fulfill({ json: [] });
  });
}

function gauge(page: Page, label: string) {
  return page.locator(".gauge").filter({ hasText: label }).locator("strong");
}

async function numericAttribute(locator: Locator, name: string) {
  const value = await locator.getAttribute(name);
  expect(value, `${name} should expose the rendered value`).not.toBeNull();
  return Number(value);
}

async function expectSynchronizedClock(page: Page) {
  const videoTime = await page.locator("video").evaluate((video: HTMLVideoElement) => video.currentTime);
  const timelineTime = Number(await page.getByLabel("Video timeline").inputValue());
  const readout = await page.locator(".plot-panel").getByLabel("Telemetry chart legend").locator("span").first().textContent();
  const readoutTime = Number(readout?.match(/([\d.]+) s$/)?.[1]);

  expect(timelineTime).toBeCloseTo(videoTime, 1);
  expect(readoutTime).toBeCloseTo(videoTime, 1);
  return videoTime;
}

test("real H.264 playback and near-edge/keyframe seeking keep rendered telemetry synchronized", async ({ page }) => {
  await mockReview(page);
  await page.goto("/?session=media-sync");

  const video = page.locator("video");
  const timeline = page.getByLabel("Video timeline");
  const map = page.getByLabel("Offline route map");
  const primaryChart = page.locator(".plot-panel > .telemetry-chart");
  const primaryReadout = primaryChart.getByLabel("Telemetry chart legend");
  const chartCursor = primaryChart.locator(".u-cursor-x");
  const chartCanvas = primaryChart.locator("canvas");

  await expect(video).toHaveJSProperty("readyState", 4);
  await expect(map).toHaveAttribute("data-position-longitude", /-?\d/);
  await expect(chartCursor).toBeAttached();

  const initialSpeed = Number(await gauge(page, "SPEED").textContent());
  const initialLongitude = await numericAttribute(map, "data-position-longitude");
  await expect(chartCursor).toHaveClass(/u-off/);
  const initialMapRendering = await map.screenshot();

  await page.getByLabel("Playback speed").selectOption("0.5");
  await page.locator(".transport").click();
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(1.6);
  await video.evaluate((element: HTMLVideoElement) => element.pause());
  await expect(video).toHaveJSProperty("paused", true);

  const playedTime = await expectSynchronizedClock(page);
  expect(playedTime).toBeGreaterThan(1.6);
  expect(playedTime).toBeLessThan(2.5);
  expect(Number(await gauge(page, "SPEED").textContent())).toBeGreaterThan(initialSpeed);
  await expect(gauge(page, "LAP")).toHaveText("2");
  const playedLongitude = await numericAttribute(map, "data-position-longitude");
  expect(playedLongitude).not.toBeCloseTo(initialLongitude, 5);
  await expect(chartCursor).not.toHaveClass(/u-off/);
  const playedCursor = (await chartCursor.boundingBox())?.x;
  expect(playedCursor).toBeGreaterThan(0);
  expect(Buffer.compare(await map.screenshot(), initialMapRendering)).not.toBe(0);

  const timelineBounds = await timeline.boundingBox();
  expect(timelineBounds).not.toBeNull();
  await timeline.click({ position: { x: (timelineBounds?.width ?? 0) * .8125, y: (timelineBounds?.height ?? 0) / 2 } });
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(3.1);
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeLessThan(3.4);

  const soughtTime = await expectSynchronizedClock(page);
  expect(soughtTime).toBeCloseTo(3.25, 0);
  await expect(gauge(page, "LAP")).toHaveText("3");
  expect(Number(await gauge(page, "SPEED").textContent())).toBeGreaterThan(playedTime * 8);
  expect(await numericAttribute(map, "data-position-longitude")).not.toBeCloseTo(playedLongitude, 5);
  expect((await chartCursor.boundingBox())?.x).toBeGreaterThan(playedCursor ?? 0);
  await expect(primaryReadout).toContainText("Speed mph");

  await video.evaluate((element: HTMLVideoElement) => { element.currentTime = .001; });
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeLessThan(.05);
  await expectSynchronizedClock(page);
  await video.evaluate((element: HTMLVideoElement) => { element.currentTime = 3.99; });
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime)).toBeGreaterThan(3.9);
  await expectSynchronizedClock(page);

  const renderedPixels = await chartCanvas.evaluate((canvas: HTMLCanvasElement) => {
    const context = canvas.getContext("2d");
    if (!context) return 0;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let visible = 0;
    for (let index = 3; index < pixels.length; index += 4) if (pixels[index] !== 0) visible += 1;
    return visible;
  });
  expect(renderedPixels).toBeGreaterThan(100);
});
