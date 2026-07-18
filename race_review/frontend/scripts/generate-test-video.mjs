import { mkdirSync, renameSync, rmSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const output = resolve("e2e/fixtures/sync-clock.mp4");
const temporary = `${output}.tmp.mp4`;
mkdirSync(dirname(output), { recursive: true });
rmSync(temporary, { force: true });

const result = spawnSync("ffmpeg", [
  "-hide_banner",
  "-loglevel", "error",
  "-f", "lavfi",
  "-i", "testsrc2=size=320x180:rate=30:duration=4",
  "-an",
  "-c:v", "libx264",
  "-preset", "veryfast",
  "-profile:v", "baseline",
  "-level:v", "3.0",
  "-pix_fmt", "yuv420p",
  "-g", "15",
  "-keyint_min", "15",
  "-sc_threshold", "0",
  "-bf", "0",
  "-movflags", "+faststart",
  "-map_metadata", "-1",
  "-y",
  temporary,
], { encoding: "utf8" });

if (result.error?.code === "ENOENT") {
  throw new Error("FFmpeg is required to generate the Playwright H.264 fixture");
}
if (result.status !== 0) {
  throw new Error(`FFmpeg could not generate the Playwright fixture:\n${result.stderr}`);
}

renameSync(temporary, output);
