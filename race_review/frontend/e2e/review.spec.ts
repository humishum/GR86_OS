import { expect, test, type Page } from "@playwright/test";

const session = {
  schema_version: 1, session_id: "demo", name: "Sonoma Raceway", created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z", status: "ready", duration_seconds: 120,
  chapters: [{ index: 0, filename: "GX010001.MP4", fingerprint: { path: "/media/GX010001.MP4", size_bytes: 1, modified_ns: 1, sha256: "0".repeat(64) }, creation_time: null, duration_seconds: 120, timeline_start_seconds: 0, timeline_end_seconds: 120, gap_before_seconds: 0, discontinuity: false }],
  streams: [], coordinate_origin: { latitude: 38.1, longitude: -122.4, altitude_m: 10, convention: "WGS84 + right-handed ENU meters" },
  processing_versions: { race_review: "test" }, processing_options: { generate_proxy: true }, artifacts: { proxy: "media/proxy.mp4", derived_telemetry: "telemetry/derived.parquet" }, warnings: [],
  edits: { track: { start_finish_a: null, start_finish_b: null, crossing_direction: 1, minimum_lap_seconds: 20, exclude_out_lap: true, exclude_in_lap: true }, calibration: { transform: { forward_axis: "x", lateral_axis: "y", forward_sign: 1, lateral_sign: 1 }, confidence: .8, method: "test", overridden: false, diagnostics: {} }, corner_edits: [], display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" } },
};

async function mockApi(
  page: Page,
  firstTelemetryOverrides: Record<number, number | boolean | null> = {},
  lapCompleteness: [boolean, boolean] = [true, true],
  lapRanges: [[number, number], [number, number]] = [[0, 60], [60, 120]],
) {
  const rows: Array<Array<number | boolean | null>> = Array.from({ length: 121 }, (_, time) => [time, 38.1 + Math.sin(time / 10) * .001, -122.4 + Math.cos(time / 10) * .001, time, time, 25, 0.1, 0.4, time * 25, time < 60 ? 1 : 2, (time % 60) * 25, true, 50 + Math.sin(time / 12) * 18, Math.sin(time / 12) * 18]);
  for (const [index, value] of Object.entries(firstTelemetryOverrides)) rows[0][Number(index)] = value;
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/telemetry")) return route.fulfill({ json: { columns: ["timestamp", "latitude", "longitude", "east_smooth_m", "north_smooth_m", "speed_mps", "longitudinal_g", "lateral_g", "distance_m", "lap_number", "lap_distance_m", "valid", "altitude_m", "up_smooth_m"], rows, start_seconds: 0, end_seconds: 120 } });
    if (url.includes("/laps")) return route.fulfill({ json: [{ lap_number: 1, start_seconds: lapRanges[0][0], end_seconds: lapRanges[0][1], lap_time_seconds: lapRanges[0][1] - lapRanges[0][0], complete: lapCompleteness[0], excluded: !lapCompleteness[0], maximum_speed_mps: 30 }, { lap_number: 2, start_seconds: lapRanges[1][0], end_seconds: lapRanges[1][1], lap_time_seconds: lapRanges[1][1] - lapRanges[1][0] - 1, complete: lapCompleteness[1], excluded: !lapCompleteness[1], maximum_speed_mps: 31 }] });
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
  await expect(page.locator('.marker--corner[data-lap-number="1"]')).toHaveCount(1);
  await expect(page.locator('.marker--corner[data-lap-number="2"]')).toHaveCount(1);
});

test("primary panels do not overlap the persistent player", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");
  const player = await page.locator(".player-bar").boundingBox();
  const stage = await page.locator(".video-stage").boundingBox();
  expect(player).not.toBeNull(); expect(stage).not.toBeNull();
  expect((stage?.y ?? 0) + (stage?.height ?? 0)).toBeLessThanOrEqual(player?.y ?? Number.MAX_VALUE);
});

test("3D track uses GoPro altitude and exposes pan, tilt, and reset controls", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Desktop camera interaction is covered here");
  await mockApi(page);
  await page.goto("/?session=demo");

  const shell = page.locator(".track-map-shell");
  const map = page.getByLabel("Offline route map");
  await expect(shell).toHaveAttribute("data-camera-mode", "3d");
  await expect(shell).toHaveAttribute("data-elevation-range", /[1-9]\d*(\.\d+)?/);
  await expect(map).toHaveAttribute("data-camera-pitch", /5[0-9]/);
  await expect(page.getByLabel("Track elevation")).toContainText("RANGE");
  await expect(page.getByLabel("Vertical exaggeration 3×")).toBeVisible();

  const initialLongitude = Number(await map.getAttribute("data-camera-longitude"));
  const canvas = map.locator("canvas");
  const box = await canvas.boundingBox();
  expect(box).not.toBeNull();
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 + 60, box.y + box.height / 2 + 25, { steps: 5 });
    await page.mouse.up();
  }
  await expect.poll(async () => Number(await map.getAttribute("data-camera-longitude"))).not.toBe(initialLongitude);

  await page.getByRole("button", { name: "TOP", exact: true }).click();
  await expect(shell).toHaveAttribute("data-camera-mode", "top");
  await expect(map).toHaveAttribute("data-camera-pitch", "0");
  await page.getByRole("button", { name: "3D", exact: true }).click();
  await expect(map).toHaveAttribute("data-camera-pitch", /5[0-9]/);
  await page.getByLabel("Vertical exaggeration 3×").click();
  await expect(page.getByLabel("Vertical exaggeration 1×")).toBeVisible();

  await page.getByLabel("Follow current position").click();
  await expect(shell).toHaveAttribute("data-follow-mode", "true");
  await page.getByLabel("Heading-up map").click();
  await expect(shell).toHaveAttribute("data-heading-up", "true");
  await expect(shell).toHaveAttribute("data-follow-mode", "true");
  await page.getByRole("button", { name: "FULL ROUTE", exact: true }).click();
  await expect(shell).toHaveAttribute("data-follow-mode", "false");

  await expect(page.getByLabel("Show lap 1")).toBeChecked();
  await page.getByLabel("Show lap 1").uncheck();
  await expect(page.getByLabel("Show lap 1")).not.toBeChecked();
  await page.getByLabel("Lap 2 color").fill("#00ff00");
  await expect(page.getByLabel("Lap 2 color")).toHaveValue("#00ff00");
});

test("sync diagnostics are opt-in and track the nearest telemetry sample", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");
  await expect(page.getByRole("complementary", { name: "Synchronization diagnostics", exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "Edit analysis" }).click();
  await page.getByLabel("Show synchronization diagnostics").check();
  await page.getByRole("button", { name: "CLOSE", exact: true }).click();

  const diagnostics = page.getByRole("complementary", { name: "Synchronization diagnostics", exact: true });
  await expect(diagnostics).toBeVisible();
  await expect(diagnostics).toContainText("0.000–120.000 s");
  await expect(diagnostics).toContainText("1.00 Hz");
  await page.locator("video").evaluate((element) => {
    Object.defineProperty(element, "currentTime", { configurable: true, value: 61.4 });
    element.dispatchEvent(new Event("seeking"));
  });
  await expect(diagnostics).toContainText("61.400 s");
  await expect(diagnostics).toContainText("61.000 s");
  await expect(diagnostics).toContainText("+400.0 ms");
  await page.getByRole("button", { name: "Close synchronization diagnostics" }).click();
  await expect(diagnostics).toHaveCount(0);
});

test("lap comparison failure is announced and can be retried", async ({ page }) => {
  await mockApi(page);
  let attempts = 0;
  await page.route("**/api/sessions/demo/comparison**", async (route) => {
    attempts += 1;
    // React StrictMode replays the initial effect in development.
    if (attempts <= 2) return route.fulfill({ status: 503, json: { detail: "Comparison service unavailable" } });
    return route.fulfill({ json: {
      distance_m: [0, 100, 200],
      reference_time_s: [0, 4, 8],
      comparison_time_s: [0, 4.1, 7.9],
      delta_s: [0, .1, -.1],
      reference_speed_mps: [20, 25, 30],
      comparison_speed_mps: [20, 24, 31],
    } });
  });
  await page.goto("/?session=demo");

  const comparisonError = page.getByRole("alert").filter({ hasText: "Could not load lap comparison" });
  await expect(comparisonError).toContainText("Comparison service unavailable");
  await comparisonError.getByRole("button", { name: "Retry comparison" }).click();
  await expect(comparisonError).toHaveCount(0);
  await expect(page.locator(".comparison .telemetry-chart")).toHaveCount(2);
});

test("failed processing actions are announced and retryable", async ({ page }) => {
  await mockApi(page);
  let cancelAttempts = 0;
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/api/sessions/demo")) {
      return route.fulfill({ json: { ...session, status: "processing" } });
    }
    if (url.endsWith("/status")) {
      return route.fulfill({ json: { session_id: "demo", status: "processing", stage: "proxy", progress: .5, message: "Building proxy", error: null, updated_at: "2026-01-01T00:00:00Z" } });
    }
    if (url.endsWith("/cancel")) {
      cancelAttempts += 1;
      return cancelAttempts === 1
        ? route.fulfill({ status: 503, json: { detail: "Cancel service unavailable" } })
        : route.fulfill({ json: { session_id: "demo", status: "cancelled" } });
    }
    return route.fallback();
  });
  await page.goto("/?session=demo");

  await page.getByRole("button", { name: "Cancel import" }).click();
  const actionError = page.getByRole("alert").filter({ hasText: "Import action failed" });
  await expect(actionError).toContainText("Cancel service unavailable");
  await actionError.getByRole("button", { name: "Retry cancellation" }).click();
  await expect(actionError).toHaveCount(0);
  expect(cancelAttempts).toBe(2);
});

test("persisted metric units drive review readouts", async ({ page }) => {
  await mockApi(page);
  await page.route("**/api/**", async (route) => {
    if (route.request().url().endsWith("/api/sessions/demo")) {
      return route.fulfill({ json: {
        ...session,
        edits: {
          ...session.edits,
          display_units: { speed: "km/h", acceleration: "m/s²", distance: "m", time: "s" },
        },
      } });
    }
    return route.fallback();
  });
  await page.goto("/?session=demo");

  const speedGauge = page.locator(".gauges .gauge").filter({ hasText: "SPEED" });
  await expect(speedGauge).toContainText("90");
  await expect(speedGauge).toContainText("KM/H");
  await expect(page.getByLabel("Lateral 3.92 m/s², longitudinal 0.98 m/s²")).toBeVisible();
  await expect(page.locator(".current-corner")).toContainText("0 M");
  await expect(page.locator(".lap-row").first()).toContainText("108 km/h");
  await expect(page.getByLabel("Track elevation")).toContainText("m");
  await expect(page.getByLabel("Telemetry chart legend").first()).toContainText("Speed km/h");
  await expect(page.getByLabel("Telemetry chart legend").first()).toContainText("Lateral m/s²");
});

test("new imports persist validated local unit defaults before opening", async ({ page }) => {
  const metricUnits = { speed: "km/h", acceleration: "m/s²", distance: "m", time: "s" };
  await page.addInitScript((units) => {
    localStorage.setItem("race-review-units", JSON.stringify(units));
  }, metricUnits);
  let savedUnits: unknown = null;
  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = request.url();
    if (url.endsWith("/api/sessions")) return route.fulfill({ json: [] });
    if (url.endsWith("/api/media")) return route.fulfill({ json: [{
      path: "/media/GX010001.MP4",
      name: "GX010001.MP4",
      size_bytes: 1_000_000,
      modified_at: "2026-01-01T00:00:00Z",
    }] });
    if (url.endsWith("/api/sessions/import")) {
      return route.fulfill({ status: 202, json: { session_id: "new-session", status: "queued" } });
    }
    if (url.endsWith("/api/sessions/new-session/display-units")) {
      savedUnits = request.postDataJSON();
      return route.fulfill({ json: {} });
    }
    if (url.endsWith("/api/sessions/new-session")) {
      return route.fulfill({ json: { ...session, session_id: "new-session", status: "queued" } });
    }
    if (url.endsWith("/status")) {
      return route.fulfill({ json: { session_id: "new-session", status: "queued", stage: "queued", progress: 0, message: "Queued", error: null, updated_at: "2026-01-01T00:00:00Z" } });
    }
    return route.fulfill({ json: [] });
  });
  await page.goto("/");
  await page.getByLabel("GX010001.MP4").check();
  await page.getByRole("button", { name: "Import session" }).click();

  await expect.poll(() => savedUnits).toEqual(metricUnits);
  await expect(page).toHaveURL(/\?session=new-session$/);
});

test("missing telemetry renders as an em dash while zero remains numeric", async ({ page }) => {
  await mockApi(page, { 5: null, 6: null, 7: 0, 9: 0 });
  await page.goto("/?session=demo");

  await expect(page.locator(".gauge").filter({ hasText: "SPEED" }).locator("strong")).toHaveText("—");
  await expect(page.getByLabel("G-force unavailable")).toBeVisible();
  await page.getByLabel("Toggle G-force display").click();
  await expect(page.getByLabel("G-force meter")).toContainText(/LONG\s+—/);
  await expect(page.getByLabel("G-force meter")).toContainText(/LAT\s+0\.00/);
  await expect(page.locator(".gauge").filter({ hasText: "LAP" }).locator("strong")).toHaveText("0");
  const chartReadout = page.locator(".plot-panel").getByLabel("Telemetry chart legend");
  await expect(chartReadout).toContainText("Speed mph —");
  await expect(chartReadout).toContainText("Lateral g 0.00");
  await expect(chartReadout).toContainText("Longitudinal g —");
});

test("G-force display toggles between a vector and exact values", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  const toggle = page.getByLabel("Toggle G-force display");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
  await expect(page.locator(".g-force-widget__ring--inner")).toHaveCount(0);
  expect(await page.locator(".g-force-widget").evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  await expect(page.getByLabel("Lateral 0.40 g, longitudinal 0.10 g")).toBeVisible();
  await toggle.click();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await expect(page.getByLabel("G-force meter")).toContainText(/LAT\s+0\.40/);
  await expect(page.getByLabel("G-force meter")).toContainText(/LONG\s+0\.10/);
});

test("long delta values remain inside their gauge", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "The compact phone overlay hides the delta gauge");
  await mockApi(page);
  await page.goto("/?session=demo");

  const delta = page.locator(".gauge").filter({ hasText: "DELTA" });
  await expect(delta.locator("strong")).toHaveText("+0.00");
  await expect(delta).toHaveClass(/gauge--compact-value/);
  const [gaugeBounds, valueBounds] = await Promise.all([delta.boundingBox(), delta.locator("strong").boundingBox()]);
  expect(gaugeBounds).not.toBeNull();
  expect(valueBounds).not.toBeNull();
  expect((valueBounds?.x ?? 0) + (valueBounds?.width ?? 0)).toBeLessThanOrEqual((gaugeBounds?.x ?? 0) + (gaugeBounds?.width ?? 0));
});

test("player can mute and restore video audio", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  await page.getByRole("button", { name: "Mute audio" }).click();
  await expect(page.locator("video")).toHaveJSProperty("muted", true);
  await page.getByRole("button", { name: "Unmute audio" }).click();
  await expect(page.locator("video")).toHaveJSProperty("muted", false);
});

test("partial opening and closing laps retain measured corner ticks", async ({ page }) => {
  await mockApi(page, {}, [false, false], [[5, 20], [65, 80]]);
  await page.goto("/?session=demo");

  await expect(page.locator('.marker--corner[data-lap-number="1"]')).toHaveCount(1);
  await expect(page.locator('.marker--corner[data-lap-number="2"]')).toHaveCount(1);
});

test("telemetry chart uses independent speed and acceleration scales", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  const chart = page.locator(".plot-panel > .telemetry-chart");
  await expect(chart).toHaveAttribute("data-scales", "speed acceleration");
  await expect(chart.locator('[data-scale="speed"]')).toContainText("Speed mph");
  await expect(chart.locator('[data-scale="acceleration"]')).toHaveCount(2);
});

test("main telemetry chart supports navigation, selection, seeking, and distance mode", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  const chart = page.locator(".plot-panel > .telemetry-chart");
  const controls = chart.getByLabel("Chart controls");
  await expect(controls.getByRole("button", { name: "INSPECT" })).toHaveAttribute("aria-pressed", "true");
  await controls.getByRole("button", { name: "ZOOM" }).click();
  await expect(chart).toHaveAttribute("data-interaction", "zoom");
  await controls.getByRole("button", { name: "PAN" }).click();
  await expect(chart).toHaveAttribute("data-interaction", "pan");
  await controls.getByRole("button", { name: "SELECT" }).click();
  await expect(chart).toHaveAttribute("data-interaction", "select");
  await controls.getByRole("button", { name: "20S WINDOW" }).click();
  await expect(chart).toHaveAttribute("data-moving-window", "true");
  await controls.getByRole("button", { name: "RESET" }).click();
  await expect(chart).toHaveAttribute("data-moving-window", "false");

  const plot = chart.locator(".u-over");
  await plot.scrollIntoViewIfNeeded();
  const bounds = await plot.boundingBox();
  expect(bounds).not.toBeNull();
  if (bounds) await page.mouse.click(bounds.x + bounds.width * .75, bounds.y + bounds.height / 2);
  await expect.poll(() => page.locator("video").evaluate((video) => (video as HTMLVideoElement).currentTime)).toBeGreaterThan(70);
  await expect(chart.getByLabel("Chart window summary")).toContainText("Point at");

  await page.getByLabel("Chart horizontal axis").getByRole("button", { name: "DISTANCE" }).click();
  await expect(chart.getByLabel("Telemetry chart legend")).toContainText("Track distance");
  await expect(chart.getByLabel("Telemetry chart legend")).toContainText("ft");
  await expect(controls.getByRole("button", { name: "20S WINDOW" })).toHaveCount(0);
});

test("chart and route readouts fit target viewport widths", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "This test explicitly covers phone through ultrawide viewports");
  await mockApi(page);
  for (const width of [320, 375, 768, 1440, 3440]) {
    await page.setViewportSize({ width, height: 900 });
    await page.goto("/?session=demo");
    const overflow = await page.evaluate(() => {
      const selectors = [
        ".plot-panel",
        ".telemetry-chart__toolbar",
        ".telemetry-chart__readout",
        ".track-map__controls",
        ".track-map__elevation",
      ];
      return {
        document: document.documentElement.scrollWidth - window.innerWidth,
        elements: selectors.map((selector) => {
          const element = document.querySelector<HTMLElement>(selector);
          return { selector, overflow: element ? element.scrollWidth - element.clientWidth : 0 };
        }),
      };
    });
    expect(overflow.document, `${width}px document overflow`).toBeLessThanOrEqual(1);
    for (const result of overflow.elements) {
      expect(result.overflow, `${width}px ${result.selector} overflow`).toBeLessThanOrEqual(1);
    }
  }
});

test("keyboard tab order is predictable and focused controls have a visible indicator", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  const libraryButton = page.getByRole("button", { name: /GR86.*REVIEW/ });
  await libraryButton.focus();
  await expect(libraryButton).toBeFocused();
  const focusStyle = await libraryButton.evaluate((element) => {
    const style = getComputedStyle(element);
    return { outlineStyle: style.outlineStyle, outlineWidth: parseFloat(style.outlineWidth) };
  });
  expect(focusStyle.outlineStyle).not.toBe("none");
  expect(focusStyle.outlineWidth).toBeGreaterThanOrEqual(2);

  await page.keyboard.press("Tab");
  await expect(page.locator("header").getByRole("button", { name: "Rebuild proxy" })).toBeFocused();

  const transport = page.getByRole("button", { name: "Play", exact: true });
  await transport.focus();
  for (const name of ["Previous event", "Previous frame", "Next frame", "Next event", "Mute audio"]) {
    await page.keyboard.press("Tab");
    await expect(page.getByRole("button", { name })).toBeFocused();
  }
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Video timeline")).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Playback speed")).toBeFocused();
});

test("analysis editor traps focus, closes with Escape, and restores trigger focus", async ({ page }) => {
  await mockApi(page);
  await page.goto("/?session=demo");

  const trigger = page.getByRole("button", { name: "Edit analysis" });
  await trigger.click();
  const dialog = page.getByRole("dialog", { name: "Analysis setup" });
  await expect(dialog).toBeVisible();
  await expect(dialog).toHaveAttribute("aria-modal", "true");

  const close = dialog.getByRole("button", { name: "CLOSE" });
  await expect(close).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(dialog.getByRole("button", { name: "Save and reanalyze" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(close).toBeFocused();

  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(trigger).toBeFocused();
});

test("analysis editor announces save failures and preserves entered values", async ({ page }) => {
  const pageErrors: Error[] = [];
  page.on("pageerror", (error) => pageErrors.push(error));
  await mockApi(page);
  await page.route("**/api/sessions/demo/track", (route) => route.fulfill({
    status: 503,
    json: { detail: "Track save is temporarily unavailable." },
  }));
  await page.goto("/?session=demo");

  await page.getByRole("button", { name: "Edit analysis" }).click();
  const dialog = page.getByRole("dialog", { name: "Analysis setup" });
  const east = dialog.getByLabel("East").first();
  await east.fill("123.4");
  await dialog.getByRole("button", { name: "Save and reanalyze" }).click();

  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("alert")).toContainText("Track save is temporarily unavailable.");
  await expect(dialog.getByRole("button", { name: "Try save again" })).toBeVisible();
  await expect(east).toHaveValue("123.4");
  expect(pageErrors).toEqual([]);
});

test("reduced-motion preference removes UI and map camera transitions", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Desktop map camera behavior is covered here");
  await page.emulateMedia({ reducedMotion: "reduce" });
  await mockApi(page);
  await page.goto("/?session=demo");

  const splitter = page.getByRole("separator", { name: "Resize track and video panels" });
  const transitionSeconds = await splitter.evaluate((element) => {
    const value = getComputedStyle(element, "::after").transitionDuration;
    return Math.max(...value.split(",").map((duration) =>
      duration.trim().endsWith("ms") ? parseFloat(duration) / 1000 : parseFloat(duration)));
  });
  expect(transitionSeconds).toBeLessThan(.01);

  await page.getByRole("button", { name: "TOP", exact: true }).click();
  await expect(page.getByLabel("Offline route map")).toHaveAttribute("data-camera-pitch", "0");
});

test("desktop review panels resize with accessible splitters", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name === "mobile", "Desktop grid splitters collapse into stacked mobile panels");
  await mockApi(page);
  await page.goto("/?session=demo");

  const stage = page.locator(".video-stage");
  const initial = await stage.boundingBox();
  await page.getByRole("separator", { name: "Resize track and video panels" }).press("ArrowLeft");
  await page.getByRole("separator", { name: "Resize video and telemetry panels" }).press("ArrowUp");
  const resized = await stage.boundingBox();
  expect(resized?.width ?? 0).toBeLessThan(initial?.width ?? 0);
  expect(resized?.height ?? 0).toBeLessThan(initial?.height ?? 0);

  const telemetryBefore = await page.locator(".plot-panel").boundingBox();
  const lapsBefore = await page.locator(".lap-panel").boundingBox();
  await page.getByRole("separator", { name: "Resize track and lap panels" }).press("ArrowUp");
  const telemetryAfter = await page.locator(".plot-panel").boundingBox();
  const lapsAfter = await page.locator(".lap-panel").boundingBox();
  expect(lapsAfter?.height ?? 0).toBeGreaterThan(lapsBefore?.height ?? 0);
  expect(telemetryAfter?.height).toBe(telemetryBefore?.height);
});
