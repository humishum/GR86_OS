import { expect, test, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { selectMediaSource } from "../src/mediaSource";
import type { SessionManifest } from "../src/types";

const media = readFileSync(
  fileURLToPath(new URL("./fixtures/sync-clock.mp4", import.meta.url)),
);

const chapter = {
  index: 0,
  filename: "GX010001.MP4",
  fingerprint: {
    path: "/fixtures/GX010001.MP4",
    size_bytes: media.length,
    modified_ns: 1,
    sha256: "0".repeat(64),
  },
  creation_time: null,
  duration_seconds: 4,
  timeline_start_seconds: 0,
  timeline_end_seconds: 4,
  gap_before_seconds: 0,
  discontinuity: false,
  streams: [{
    index: 0,
    codec_type: "video",
    codec_name: "hevc",
    codec_tag: "hvc1",
    duration_seconds: 4,
    frame_rate: 30,
    width: 3840,
    height: 2160,
  }],
};

const session: SessionManifest = {
  schema_version: 1,
  session_id: "source-policy",
  name: "Source Policy",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  status: "ready",
  duration_seconds: 4,
  chapters: [chapter],
  streams: [],
  coordinate_origin: {
    latitude: 38.16,
    longitude: -122.46,
    altitude_m: 10,
    convention: "WGS84 + right-handed ENU meters",
  },
  processing_versions: { race_review: "test" },
  processing_options: { generate_proxy: true },
  artifacts: {
    proxy: "media/proxy.mp4",
    derived_telemetry: "telemetry/derived.parquet",
  },
  warnings: [],
  edits: {
    track: {
      start_finish_a: null,
      start_finish_b: null,
      crossing_direction: 1,
      minimum_lap_seconds: 1,
      exclude_out_lap: false,
      exclude_in_lap: false,
    },
    calibration: {
      transform: {
        forward_axis: "x",
        lateral_axis: "y",
        forward_sign: 1,
        lateral_sign: 1,
      },
      confidence: .8,
      method: "test",
      overridden: false,
      diagnostics: {},
    },
    corner_edits: [],
    display_units: { speed: "mph", acceleration: "g", distance: "ft", time: "s" },
  },
};

const telemetry = {
  columns: [
    "timestamp",
    "latitude",
    "longitude",
    "east_smooth_m",
    "north_smooth_m",
    "speed_mps",
    "longitudinal_g",
    "lateral_g",
    "distance_m",
    "lap_number",
    "lap_distance_m",
    "valid",
  ],
  rows: [
    [0, 38.16, -122.46, 0, 0, 5, 0, 0, 0, 1, 0, true],
    [4, 38.1601, -122.4599, 10, 10, 10, 0, 0, 40, 1, 40, true],
  ],
  start_seconds: 0,
  end_seconds: 4,
};

async function fulfillMedia(route: Route) {
  const match = route.request().headers().range?.match(/^bytes=(\d+)-(\d*)$/);
  if (!match) {
    await route.fulfill({ body: media, contentType: "video/mp4" });
    return;
  }
  const start = Number(match[1]);
  const end = match[2] ? Math.min(Number(match[2]), media.length - 1) : media.length - 1;
  await route.fulfill({
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

async function mockReview(
  page: Page,
  value: SessionManifest,
  options: { hvc1: boolean; failSource?: boolean },
) {
  await page.addInitScript((supported) => {
    Object.defineProperty(HTMLMediaElement.prototype, "canPlayType", {
      configurable: true,
      value(mediaType: string) {
        if (mediaType.includes("hvc1")) return supported ? "probably" : "";
        return "probably";
      },
    });
  }, options.hvc1);
  const requests = { source: 0, proxy: 0 };
  await page.route("**/api/**", async (route) => {
    const url = route.request().url();
    if (url.endsWith("/media/source")) {
      requests.source += 1;
      if (options.failSource) {
        await route.fulfill({ status: 500, body: "source failure" });
      } else {
        await fulfillMedia(route);
      }
      return;
    }
    if (url.endsWith("/media/proxy")) {
      requests.proxy += 1;
      await fulfillMedia(route);
      return;
    }
    if (url.includes("/telemetry")) {
      await route.fulfill({ json: telemetry });
      return;
    }
    if (url.includes("/laps") || url.includes("/corners")) {
      await route.fulfill({ json: [] });
      return;
    }
    if (url.endsWith(`/api/sessions/${value.session_id}`)) {
      await route.fulfill({ json: value });
      return;
    }
    await route.fulfill({ json: [] });
  });
  return requests;
}

test("media source policy selects direct, fallback, and multi-chapter proxy URLs", () => {
  const supported = selectMediaSource(
    session.session_id,
    session,
    (mediaType) => mediaType.includes("hvc1") ? "probably" : "",
  );
  expect(supported).toEqual({
    kind: "source",
    url: `/api/sessions/${session.session_id}/media/source`,
    fallbackUrl: `/api/sessions/${session.session_id}/media/proxy`,
  });

  const unsupported = selectMediaSource(session.session_id, session, () => "");
  expect(unsupported).toEqual({
    kind: "proxy",
    url: `/api/sessions/${session.session_id}/media/proxy`,
    fallbackUrl: null,
  });

  const multi: SessionManifest = {
    ...session,
    chapters: [
      chapter,
      {
        ...chapter,
        index: 1,
        timeline_start_seconds: 4,
        timeline_end_seconds: 8,
      },
    ],
  };
  expect(selectMediaSource(multi.session_id, multi, () => "probably").kind).toBe("proxy");
});

test("uses the original one-chapter hvc1 source when the browser supports it", async ({
  page,
}) => {
  const requests = await mockReview(page, session, { hvc1: true });
  await page.goto(`/?session=${session.session_id}`);

  const video = page.locator("video");
  await expect(video).toHaveAttribute("data-media-source", "source");
  await expect(video).toHaveAttribute("src", /\/media\/source$/);
  await expect(video).toHaveJSProperty("readyState", 4);
  expect(requests.source).toBeGreaterThan(0);
  expect(requests.proxy).toBe(0);
});

test("falls back to the proxy when direct source loading fails", async ({ page }) => {
  const requests = await mockReview(page, session, { hvc1: true, failSource: true });
  await page.goto(`/?session=${session.session_id}`);

  const video = page.locator("video");
  await expect(video).toHaveAttribute("data-media-source", "proxy");
  await expect(video).toHaveAttribute("src", /\/media\/proxy$/);
  await expect(video).toHaveJSProperty("readyState", 4);
  expect(requests.source).toBeGreaterThan(0);
  expect(requests.proxy).toBeGreaterThan(0);
});

test("keeps the proxy mandatory without hvc1 support and for multiple chapters", async ({
  page,
}) => {
  const unsupported = await mockReview(page, session, { hvc1: false });
  await page.goto(`/?session=${session.session_id}`);
  await expect(page.locator("video")).toHaveAttribute("data-media-source", "proxy");
  expect(unsupported.source).toBe(0);
  expect(unsupported.proxy).toBeGreaterThan(0);

  const secondChapter = {
    ...chapter,
    index: 1,
    timeline_start_seconds: 4,
    timeline_end_seconds: 8,
  };
  const multi = {
    ...session,
    session_id: "source-policy-multi",
    duration_seconds: 8,
    chapters: [chapter, secondChapter],
  };
  const supported = await mockReview(page, multi, { hvc1: true });
  await page.goto(`/?session=${multi.session_id}`);
  await expect(page.locator("video")).toHaveAttribute("data-media-source", "proxy");
  expect(supported.source).toBe(0);
  expect(supported.proxy).toBeGreaterThan(0);
});
