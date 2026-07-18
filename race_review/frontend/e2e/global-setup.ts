import { execFileSync } from "node:child_process";

export default function globalSetup() {
  execFileSync(process.execPath, ["scripts/generate-test-video.mjs"], {
    cwd: process.cwd(),
    stdio: "inherit",
  });
}
