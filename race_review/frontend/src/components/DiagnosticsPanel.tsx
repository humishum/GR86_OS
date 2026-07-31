import { telemetryNumber, type TelemetrySample } from "../telemetry";

type Diagnostics = {
  start: number | null;
  end: number | null;
  sampleRate: number | null;
  nearest: number | null;
  bracketStart: number | null;
  bracketEnd: number | null;
  interpolated: number | null;
  drift: number | null;
};

function calculateDiagnostics(samples: TelemetrySample[], videoTime: number): Diagnostics {
  const timestamps = samples
    .map((sample) => telemetryNumber(sample.timestamp))
    .filter((timestamp): timestamp is number => timestamp != null);
  if (!timestamps.length) return {
    start: null, end: null, sampleRate: null, nearest: null,
    bracketStart: null, bracketEnd: null, interpolated: null, drift: null,
  };
  const start = timestamps[0];
  const end = timestamps[timestamps.length - 1];
  const sampleRate = timestamps.length > 1 && end > start ? (timestamps.length - 1) / (end - start) : null;
  let nearest = timestamps[0];
  for (const timestamp of timestamps) {
    if (Math.abs(timestamp - videoTime) < Math.abs(nearest - videoTime)) nearest = timestamp;
  }
  const afterIndex = timestamps.findIndex((timestamp) => timestamp >= videoTime);
  const beforeIndex = afterIndex < 0 ? timestamps.length - 1 : Math.max(0, afterIndex - 1);
  const bracketStart = timestamps[beforeIndex];
  const bracketEnd = timestamps[afterIndex < 0 ? timestamps.length - 1 : afterIndex];
  const interpolated = Math.min(Math.max(videoTime, bracketStart), bracketEnd);
  return {
    start, end, sampleRate, nearest, bracketStart, bracketEnd, interpolated,
    drift: videoTime - nearest,
  };
}

const seconds = (value: number | null) => value == null ? "—" : `${value.toFixed(3)} s`;

export function DiagnosticsPanel({ samples, videoTime, video, onClose }: { samples: TelemetrySample[]; videoTime: number; video: HTMLVideoElement | null; onClose: () => void }) {
  const diagnostics = calculateDiagnostics(samples, videoTime);
  return <aside className="diagnostics-panel" aria-label="Synchronization diagnostics">
    <div className="section-heading"><h2>Sync diagnostics</h2><button className="diagnostics-panel__close" onClick={onClose} aria-label="Close synchronization diagnostics">×</button></div>
    <dl>
      <div><dt>Telemetry range</dt><dd>{diagnostics.start == null || diagnostics.end == null ? "—" : `${diagnostics.start.toFixed(3)}–${diagnostics.end.toFixed(3)} s`}</dd></div>
      <div><dt>Sample rate</dt><dd>{diagnostics.sampleRate == null ? "—" : `${diagnostics.sampleRate.toFixed(2)} Hz`}</dd></div>
      <div><dt>Video time</dt><dd>{seconds(videoTime)}</dd></div>
      <div><dt>Sample bracket</dt><dd>{diagnostics.bracketStart == null || diagnostics.bracketEnd == null ? "—" : `${diagnostics.bracketStart.toFixed(3)}–${diagnostics.bracketEnd.toFixed(3)} s`}</dd></div>
      <div><dt>Interpolated time</dt><dd>{seconds(diagnostics.interpolated)}</dd></div>
      <div><dt>Nearest sample</dt><dd>{seconds(diagnostics.nearest)}</dd></div>
      <div><dt>Video frame callback</dt><dd>{video && "requestVideoFrameCallback" in video ? "SUPPORTED" : "UNAVAILABLE"}</dd></div>
      <div><dt>Drift</dt><dd>{diagnostics.drift == null ? "—" : `${diagnostics.drift >= 0 ? "+" : ""}${(diagnostics.drift * 1000).toFixed(1)} ms`}</dd></div>
    </dl>
  </aside>;
}
