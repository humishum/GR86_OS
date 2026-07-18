import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { EditPanel } from "./components/EditPanel";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { Gauges } from "./components/Gauges";
import { ImportPanel } from "./components/ImportPanel";
import { LapPanel } from "./components/LapPanel";
import { ResizableReviewGrid } from "./components/ResizableReviewGrid";
import { Scrubber } from "./components/Scrubber";
import { TelemetryChart } from "./components/TelemetryChart";
import { TrackMap } from "./components/TrackMap";
import type { CornerSummary, JobStatus, LapSummary, SessionManifest } from "./types";
import { useVideoClock } from "./hooks/useVideoClock";
import { usePlaybackShortcuts } from "./hooks/usePlaybackShortcuts";
import { feet, interpolateTelemetry, mph, telemetryNumber, unpackTelemetry, type TelemetrySample } from "./telemetry";

function deltaAt(samples: TelemetrySample[], current: TelemetrySample | null, laps: LapSummary[]) {
  const lapNumber = Number(current?.lap_number ?? 0);
  const distance = Number(current?.lap_distance_m ?? NaN);
  const currentLap = laps.find((lap) => lap.lap_number === lapNumber);
  const reference = laps.filter((lap) => lap.complete && !lap.excluded).sort((a, b) => a.lap_time_seconds - b.lap_time_seconds)[0];
  if (!currentLap || !reference || reference.lap_number === lapNumber || !Number.isFinite(distance)) return null;
  const referenceSamples = samples.filter((sample) => Number(sample.lap_number) === reference.lap_number);
  let nearest = referenceSamples[0];
  for (const sample of referenceSamples) if (Math.abs(Number(sample.lap_distance_m) - distance) < Math.abs(Number(nearest?.lap_distance_m) - distance)) nearest = sample;
  if (!nearest) return null;
  return Number(current?.timestamp) - currentLap.start_seconds - (Number(nearest.timestamp) - reference.start_seconds);
}

function Review({ sessionId, onBack }: { sessionId: string; onBack: () => void }) {
  const [session, setSession] = useState<SessionManifest | null>(null);
  const [job, setJob] = useState<JobStatus | null>(null);
  const [samples, setSamples] = useState<TelemetrySample[]>([]);
  const [laps, setLaps] = useState<LapSummary[]>([]);
  const [corners, setCorners] = useState<CornerSummary[]>([]);
  const [error, setError] = useState("");
  const [showDiagnostics, setShowDiagnostics] = useState(false);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const attachVideo = useCallback((element: HTMLVideoElement | null) => setVideo(element), []);
  const time = useVideoClock(video);
  usePlaybackShortcuts({ video, duration: session?.duration_seconds ?? 0, laps, onPlaybackRateChange: setPlaybackRate });
  const current = useMemo(() => interpolateTelemetry(samples, time), [samples, time]);
  const delta = useMemo(() => deltaAt(samples, current, laps), [samples, current, laps]);
  const load = useCallback(async () => {
    const next = await api.session(sessionId); setSession(next);
    if (next.status === "ready") {
      const [telemetry, nextLaps, nextCorners] = await Promise.all([api.telemetry(sessionId), api.laps(sessionId), api.corners(sessionId)]);
      setSamples(unpackTelemetry(telemetry)); setLaps(nextLaps); setCorners(nextCorners);
    }
  }, [sessionId]);
  useEffect(() => { load().catch((reason) => setError(reason.message)); }, [load]);
  useEffect(() => {
    if (session?.status === "ready" || session?.status === "failed") return;
    const timer = window.setInterval(async () => {
      const status = await api.status(sessionId); setJob(status);
      if (status.status === "ready" || status.status === "failed") await load();
    }, 1000);
    return () => clearInterval(timer);
  }, [session?.status, sessionId, load]);
  const seek = (seconds: number) => { if (video) video.currentTime = seconds; };
  const togglePlayback = () => { if (!video) return; if (video.paused) void video.play(); else video.pause(); };
  const chartData = useMemo(() => ({
    x: samples.map((sample) => Number(sample.timestamp)),
    series: [
      { label: "Speed mph", values: samples.map((sample) => mph(telemetryNumber(sample.speed_mps))), color: "#f2f5f6", scale: "speed" },
      { label: "Lateral g", values: samples.map((sample) => telemetryNumber(sample.lateral_g)), color: "#ff5038", scale: "acceleration" },
      { label: "Longitudinal g", values: samples.map((sample) => telemetryNumber(sample.longitudinal_g)), color: "#ffb238", scale: "acceleration" },
    ],
  }), [samples]);
  if (!session) return <main className="loading">{error || "Loading race review…"}</main>;
  if (session.status !== "ready") return <main className="processing-screen"><div className="wordmark"><span>GR86</span> / RACE REVIEW</div><section>
    <p className="eyebrow">{session.status.toUpperCase()}</p><h1>{session.name}</h1><div className="progress"><i style={{ width: `${(job?.progress ?? 0) * 100}%` }} /></div>
    <strong>{job?.message ?? "Preparing source chapters"}</strong><small>{job?.stage ?? "queued"} · {Math.round((job?.progress ?? 0) * 100)}% overall</small>
    {job?.error && <p className="error">{job.error}</p>}<button className="secondary" onClick={onBack}>Session library</button>
  </section></main>;
  return <main className="review-shell">
    <header className="topbar"><button className="wordmark wordmark--button" onClick={onBack}><span>GR86</span> / REVIEW</button><div className="topbar__session"><strong>{session.name}</strong><small>{session.chapters.length} CHAPTER{session.chapters.length === 1 ? "" : "S"}</small></div><EditPanel session={session} corners={corners} onSaved={load} showDiagnostics={showDiagnostics} onShowDiagnosticsChange={setShowDiagnostics} /></header>
    {!!session.warnings.length && <div className="warning-bar">{session.warnings[0]}</div>}
    <ResizableReviewGrid>
      <section className="video-stage">
        <video ref={attachVideo} src={`/api/sessions/${sessionId}/media/proxy`} preload="metadata" playsInline onClick={togglePlayback} />
        <Gauges sample={current} delta={delta} />
        {showDiagnostics && <DiagnosticsPanel samples={samples} videoTime={time} onClose={() => setShowDiagnostics(false)} />}
        <button className="play-button" onClick={togglePlayback} aria-label="Play or pause">{video?.paused === false ? "Ⅱ" : "▶"}</button>
      </section>
      <aside className="track-panel"><div className="section-heading"><h2>Track</h2><span>OFFLINE ROUTE</span></div><TrackMap samples={samples} current={current} corners={corners} track={session.edits.track} />
        <div className="current-corner"><small>NEXT · {feet(telemetryNumber(current?.lap_distance_m))?.toFixed(0) ?? "—"} FT</small><strong>{telemetryNumber(current?.lap_distance_m) == null ? "—" : corners.find((corner) => corner.apex_distance_m > Number(current?.lap_distance_m))?.name ?? corners[0]?.name ?? "—"}</strong></div>
      </aside>
      <section className="plot-panel"><div className="section-heading"><h2>Telemetry</h2><span>VIDEO TIME</span></div><TelemetryChart x={chartData.x} series={chartData.series} cursor={time} xLabel="Time" /></section>
      <LapPanel sessionId={sessionId} laps={laps} onSeek={seek} />
    </ResizableReviewGrid>
    <footer className="player-bar"><button className="transport" onClick={togglePlayback}>▶ / Ⅱ</button><Scrubber time={time} duration={session.duration_seconds} chapters={session.chapters} laps={laps} corners={corners} onSeek={seek} />
      <select aria-label="Playback speed" value={playbackRate} onChange={(event) => { const rate = Number(event.target.value); if (video) video.playbackRate = rate; setPlaybackRate(rate); }}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></footer>
  </main>;
}

export default function App() {
  const [sessions, setSessions] = useState<SessionManifest[]>([]);
  const [active, setActive] = useState<string | null>(() => new URLSearchParams(location.search).get("session"));
  const [importing, setImporting] = useState(false);
  useEffect(() => {
    if (!localStorage.getItem("race-review-units")) {
      localStorage.setItem("race-review-units", JSON.stringify({ speed: "mph", acceleration: "g", distance: "ft", time: "s" }));
    }
  }, []);
  const refresh = () => api.sessions().then(setSessions).catch(() => setSessions([]));
  useEffect(() => { void refresh(); }, []);
  const open = (id: string) => { setActive(id); setImporting(false); history.replaceState(null, "", `?session=${id}`); };
  if (active) return <Review sessionId={active} onBack={() => { setActive(null); refresh(); history.replaceState(null, "", location.pathname); }} />;
  if (importing || !sessions.length) return <ImportPanel onCreated={open} />;
  return <main className="library"><header><div className="wordmark"><span>GR86</span> / RACE REVIEW</div><button className="primary" onClick={() => setImporting(true)}>New import</button></header><section><p className="eyebrow">LOCAL SESSIONS</p><h1>Race library</h1><div className="session-grid">{sessions.map((session) => <button key={session.session_id} className="session-card" onClick={() => open(session.session_id)}>
    <div className="session-card__image" style={{ backgroundImage: `url(/api/sessions/${session.session_id}/thumbnail)` }}><span>{session.status}</span></div><div><strong>{session.name}</strong><small>{new Date(session.created_at).toLocaleDateString()} · {(session.duration_seconds / 60).toFixed(1)} min</small></div>
  </button>)}</div></section></main>;
}
