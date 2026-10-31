import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import { ActionableError, errorMessage } from "./components/ActionableError";
import { ConfirmDialog } from "./components/ConfirmDialog";
import { DiagnosticsPanel } from "./components/DiagnosticsPanel";
import { Gauges } from "./components/Gauges";
import { ImportPanel } from "./components/ImportPanel";
import { ResizableReviewGrid } from "./components/ResizableReviewGrid";
import { Scrubber } from "./components/Scrubber";
import { TelemetryChart } from "./components/TelemetryChart";
import type { Bookmark, CornerSummary, JobStatus, LapSummary, SessionManifest } from "./types";
import { useVideoClock } from "./hooks/useVideoClock";
import { usePlaybackShortcuts } from "./hooks/usePlaybackShortcuts";
import { selectMediaSource, type MediaSourceSelection } from "./mediaSource";
import { formatTime, interpolateTelemetry, telemetryNumber, unpackTelemetry, type TelemetrySample } from "./telemetry";
import { accelerationUnitLabel, displayAcceleration, displayDistance, displaySpeed, distanceUnitLabel, speedUnitLabel, storedDisplayUnits } from "./displayUnits";

const EditPanel = lazy(() => import("./components/EditPanel").then((module) => ({ default: module.EditPanel })));
const LapPanel = lazy(() => import("./components/LapPanel").then((module) => ({ default: module.LapPanel })));
const TrackMap = lazy(() => import("./components/TrackMap").then((module) => ({ default: module.TrackMap })));

function deltaAt(samples: TelemetrySample[], current: TelemetrySample | null, laps: LapSummary[], referenceLapNumber?: number | null) {
  const lapNumber = Number(current?.lap_number ?? 0);
  const distance = Number(current?.lap_distance_m ?? NaN);
  const currentLap = laps.find((lap) => lap.lap_number === lapNumber);
  const preferred = referenceLapNumber == null
    ? undefined
    : laps.find((lap) => lap.lap_number === referenceLapNumber && lap.complete && !lap.excluded);
  const reference = preferred ?? laps.filter((lap) => lap.complete && !lap.excluded).sort((a, b) => a.lap_time_seconds - b.lap_time_seconds)[0];
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
  const [chartMode, setChartMode] = useState<"time" | "distance">("time");
  const [chartPreviewTime, setChartPreviewTime] = useState<number | null>(null);
  const [video, setVideo] = useState<HTMLVideoElement | null>(null);
  const [playbackRate, setPlaybackRate] = useState(1);
  const [playbackState, setPlaybackState] = useState<"playing" | "paused" | "ended">("paused");
  const [muted, setMuted] = useState(false);
  const [mediaError, setMediaError] = useState("");
  const [actionBusy, setActionBusy] = useState(false);
  const [failedProcessingAction, setFailedProcessingAction] = useState<"retry" | "cancel" | null>(null);
  const [relocationPath, setRelocationPath] = useState("");
  const [theater, setTheater] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [ghost, setGhost] = useState<TelemetrySample | null>(null);
  const resumeAfterBackground = useRef(false);
  const videoStage = useRef<HTMLElement | null>(null);
  const attachVideo = useCallback((element: HTMLVideoElement | null) => setVideo(element), []);
  const time = useVideoClock(video);
  const toggleTheater = useCallback(() => setTheater((value) => !value), []);
  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) void document.exitFullscreen();
    else void videoStage.current?.requestFullscreen();
  }, []);
  usePlaybackShortcuts({
    video,
    duration: session?.duration_seconds ?? 0,
    laps,
    corners,
    onPlaybackRateChange: setPlaybackRate,
    onTheaterToggle: toggleTheater,
    onFullscreenToggle: toggleFullscreen,
  });
  const preferredMedia = useMemo(() => session
    ? selectMediaSource(sessionId, session, (mediaType) => document.createElement("video").canPlayType(mediaType))
    : null, [session, sessionId]);
  const [media, setMedia] = useState<MediaSourceSelection | null>(null);
  useEffect(() => { setMedia(preferredMedia); }, [preferredMedia]);
  useEffect(() => {
    if (!video) return;
    const update = () => setPlaybackState(video.ended ? "ended" : video.paused ? "paused" : "playing");
    for (const event of ["play", "pause", "ended", "loadedmetadata"]) video.addEventListener(event, update);
    update();
    return () => {
      for (const event of ["play", "pause", "ended", "loadedmetadata"]) video.removeEventListener(event, update);
    };
  }, [video]);
  useEffect(() => {
    if (!video) return;
    const handleVisibility = () => {
      if (document.visibilityState === "hidden") {
        resumeAfterBackground.current = !video.paused && !video.ended;
        if (resumeAfterBackground.current) video.pause();
      } else if (resumeAfterBackground.current) {
        resumeAfterBackground.current = false;
        void video.play().catch(() => undefined);
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [video]);
  useEffect(() => {
    const update = () => setFullscreen(Boolean(document.fullscreenElement));
    document.addEventListener("fullscreenchange", update);
    return () => document.removeEventListener("fullscreenchange", update);
  }, []);
  const current = useMemo(() => interpolateTelemetry(samples, time), [samples, time]);
  const displayedCurrent = useMemo(
    () => interpolateTelemetry(samples, chartPreviewTime ?? time),
    [chartPreviewTime, samples, time],
  );
  const delta = useMemo(
    () => deltaAt(samples, current, laps, session?.edits.reference_lap),
    [current, laps, samples, session?.edits.reference_lap],
  );
  const displayUnits = session?.edits.display_units;
  const load = useCallback(async () => {
    const next = await api.session(sessionId); setSession(next);
    if (next.status === "ready") {
      const [telemetry, nextLaps, nextCorners] = await Promise.all([api.telemetry(sessionId), api.laps(sessionId), api.corners(sessionId)]);
      setSamples(unpackTelemetry(telemetry)); setLaps(nextLaps); setCorners(nextCorners);
    }
  }, [sessionId]);
  useEffect(() => {
    void load()
      .then(() => setError(""))
      .catch((reason) => setError(errorMessage(reason, "Could not load this race review.")));
  }, [load]);
  useEffect(() => {
    if (session?.status === "ready" || session?.status === "failed") return;
    const timer = window.setInterval(() => {
      void api.status(sessionId).then(async (status) => {
        setJob(status);
        if (status.status === "ready" || status.status === "failed") await load();
        setError("");
      }).catch((reason) => {
        setError(errorMessage(reason, "Could not update import progress."));
      });
    }, 1000);
    return () => clearInterval(timer);
  }, [session?.status, sessionId, load]);
  const seek = (seconds: number) => { if (video) video.currentTime = seconds; };
  const runProcessingAction = async (action: "retry" | "cancel") => {
    setActionBusy(true); setError(""); setFailedProcessingAction(null);
    try {
      if (action === "retry") await api.retryImport(sessionId);
      else await api.cancelImport(sessionId);
      await load();
    } catch (reason) {
      setFailedProcessingAction(action);
      setError(errorMessage(
        reason,
        action === "retry" ? "Could not retry the import." : "Could not cancel the import.",
      ));
    } finally {
      setActionBusy(false);
    }
  };
  const seekFrame = (direction: -1 | 1) => {
    if (!video) return;
    video.pause();
    seek(video.currentTime + direction * (1001 / 60000));
  };
  const eventTimes = useMemo(() => [...new Set([
    ...laps.flatMap((lap) => [lap.start_seconds, lap.end_seconds]),
    ...corners.flatMap((corner) => [corner.entry_seconds, corner.apex_seconds, corner.exit_seconds]),
  ].filter((value): value is number => value != null && Number.isFinite(value)))].sort((a, b) => a - b), [corners, laps]);
  const seekEvent = (direction: -1 | 1) => {
    if (!video) return;
    const next = direction > 0
      ? eventTimes.find((value) => value > video.currentTime + .001)
      : [...eventTimes].reverse().find((value) => value < video.currentTime - .001);
    if (next != null) seek(next);
  };
  const togglePlayback = () => { if (!video) return; if (video.paused) void video.play(); else video.pause(); };
  const chartData = useMemo(() => ({
    x: samples.map((sample) => chartMode === "time"
      ? Number(sample.timestamp)
      : displayUnits ? displayDistance(telemetryNumber(sample.distance_m), displayUnits) ?? 0 : 0),
    series: [
      { label: `Speed ${displayUnits ? speedUnitLabel(displayUnits) : ""}`, values: samples.map((sample) => displayUnits ? displaySpeed(telemetryNumber(sample.speed_mps), displayUnits) : null), color: "#f2f5f6", scale: "speed" },
      { label: `Lateral ${displayUnits ? accelerationUnitLabel(displayUnits) : ""}`, values: samples.map((sample) => displayUnits ? displayAcceleration(telemetryNumber(sample.lateral_g), displayUnits) : null), color: "#ff5038", scale: "acceleration" },
      { label: `Longitudinal ${displayUnits ? accelerationUnitLabel(displayUnits) : ""}`, values: samples.map((sample) => displayUnits ? displayAcceleration(telemetryNumber(sample.longitudinal_g), displayUnits) : null), color: "#ffb238", scale: "acceleration" },
    ],
  }), [chartMode, displayUnits, samples]);
  const chartCursor = chartMode === "time"
    ? chartPreviewTime ?? time
    : displayUnits ? displayDistance(telemetryNumber(displayedCurrent?.distance_m), displayUnits) ?? undefined : undefined;
  const previewChartIndex = useCallback((index: number | null) => {
    setChartPreviewTime(index == null ? null : Number(samples[index]?.timestamp));
  }, [samples]);
  const seekChartIndex = useCallback((index: number) => {
    const nextTime = Number(samples[index]?.timestamp);
    if (Number.isFinite(nextTime)) seek(nextTime);
  }, [samples, video]);
  const saveReferenceLap = async (lap: number) => {
    try {
      setSession(await api.saveReferenceLap(sessionId, lap));
      setError("");
    } catch (reason) {
      setError(errorMessage(reason, "Could not save the reference lap."));
    }
  };
  const saveBookmarks = async (bookmarks: Bookmark[]) => {
    setSession(await api.saveBookmarks(sessionId, bookmarks));
  };
  const nextCornerName = corners.find((corner) => corner.apex_distance_m > Number(displayedCurrent?.lap_distance_m))?.name
    ?? corners[0]?.name
    ?? "—";
  if (!session) return <main className="loading">{error
    ? <ActionableError
        title="Could not load race review"
        message={error}
        primaryAction={{ label: "Retry", onClick: () => void load().then(() => setError("")).catch((reason) => setError(errorMessage(reason))) }}
        secondaryAction={{ label: "Session library", onClick: onBack }}
      />
    : <span role="status">Loading race review…</span>}
  </main>;
  if (session.status !== "ready") return <main className="processing-screen"><div className="wordmark"><span>GR86</span> / RACE REVIEW</div><section>
    <p className="eyebrow">{session.status.toUpperCase()}</p><h1>{session.name}</h1><div className="progress"><i style={{ width: `${(job?.progress ?? 0) * 100}%` }} /></div>
    <strong>{job?.message ?? "Preparing source chapters"}</strong><small>{job?.stage ?? "queued"} · {Math.round((job?.progress ?? 0) * 100)}% overall</small>
    {(job?.error || error) && <ActionableError
      compact
      title={job?.error ? "Import processing failed" : "Import action failed"}
      message={error || job?.error || "The import could not continue."}
      primaryAction={failedProcessingAction === "cancel"
        ? { label: "Retry cancellation", onClick: () => void runProcessingAction("cancel"), disabled: actionBusy }
        : { label: "Retry import", onClick: () => void runProcessingAction("retry"), disabled: actionBusy }}
    />}<div className="processing-actions">
      {(session.status === "failed" || session.status === "cancelled") && <button className="primary" disabled={actionBusy} onClick={() => void runProcessingAction("retry")}>Retry import</button>}
      {(session.status === "processing" || session.status === "queued") && <button className="secondary" disabled={actionBusy} onClick={() => void runProcessingAction("cancel")}>Cancel import</button>}
      <button className="secondary" onClick={onBack}>Session library</button>
    </div>
  </section></main>;
  const staleWarning = session.warnings.find((warning) => warning.startsWith("Source is missing or stale:"));
  const stalePath = staleWarning?.slice("Source is missing or stale:".length).trim();
  const staleChapter = session.chapters.find((chapter) => chapter.fingerprint.path === stalePath);
  return <main className="review-shell" data-theater={theater} data-fullscreen={fullscreen}>
    <header className="topbar"><button className="wordmark wordmark--button" onClick={onBack}><span>GR86</span> / REVIEW</button><div className="topbar__session"><strong>{session.name}</strong><small>{session.chapters.length} CHAPTER{session.chapters.length === 1 ? "" : "S"}</small></div><div className="topbar__actions"><button className="proxy-rebuild" type="button" disabled={actionBusy} onClick={async () => {
      setActionBusy(true); setError("");
      try {
        await api.exportBundle(sessionId);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Export failed");
      } finally {
        setActionBusy(false);
      }
    }}>Export</button><button className="proxy-rebuild" type="button" disabled={actionBusy} onClick={async () => {
      setActionBusy(true); setError("");
      try {
        await api.rebuildProxy(sessionId);
        setSession((currentSession) => currentSession ? { ...currentSession, status: "processing" } : currentSession);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Proxy rebuild failed");
      } finally {
        setActionBusy(false);
      }
    }}>Rebuild proxy</button><Suspense fallback={<button className="icon-button" type="button" disabled aria-label="Loading analysis editor">TUNE</button>}><EditPanel session={session} corners={corners} onSaved={load} showDiagnostics={showDiagnostics} onShowDiagnosticsChange={setShowDiagnostics} /></Suspense></div></header>
    {(error || !!session.warnings.length) && <div className="warning-bar" role={error ? "alert" : "status"}><span>{error || session.warnings[0]}</span>{staleChapter && <form onSubmit={async (event) => {
      event.preventDefault();
      setActionBusy(true); setError("");
      try {
        const relocated = await api.relocateSource(sessionId, staleChapter.index, relocationPath);
        setSession(relocated); setRelocationPath("");
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Source relocation failed");
      } finally {
        setActionBusy(false);
      }
    }}><input aria-label="Relocated source path" value={relocationPath} onChange={(event) => setRelocationPath(event.target.value)} placeholder="/media/new/GX010001.MP4" /><button type="submit" disabled={!relocationPath || actionBusy}>Relocate source</button></form>}</div>}
    <ResizableReviewGrid theater={theater}>
      <section className="video-stage" ref={videoStage}>
        <video
          ref={attachVideo}
          src={media?.url}
          data-media-source={media?.kind}
          preload="metadata"
          playsInline
          muted={muted}
          onError={() => {
            if (media?.kind === "source" && media.fallbackUrl) {
              setMediaError("Original HERO10 media could not be played. Using the compatibility proxy.");
              setMedia({ kind: "proxy", url: media.fallbackUrl, fallbackUrl: null });
            } else {
              setMediaError("Compatibility proxy playback failed.");
            }
          }}
          onClick={togglePlayback}
        />
        <Gauges sample={displayedCurrent} delta={delta} units={session.edits.display_units} />
        {showDiagnostics && <DiagnosticsPanel samples={samples} videoTime={time} video={video} onClose={() => setShowDiagnostics(false)} />}
        {mediaError && <div className="media-error"><span role="alert">{mediaError}</span><button type="button" onClick={() => {
          setMediaError("");
          if (preferredMedia?.kind === "source") setMedia({ ...preferredMedia, url: `${preferredMedia.url}?retry=${Date.now()}` });
          else video?.load();
        }}>{preferredMedia?.kind === "source" ? "Retry original" : "Retry proxy"}</button><button type="button" disabled={actionBusy} onClick={async () => {
          setActionBusy(true); setError("");
          try {
            await api.rebuildProxy(sessionId);
            setMediaError("");
            setSession((currentSession) => currentSession ? { ...currentSession, status: "processing" } : currentSession);
          } catch (reason) {
            setMediaError(errorMessage(reason, "Could not rebuild the compatibility proxy."));
          } finally {
            setActionBusy(false);
          }
        }}>Rebuild compatibility proxy</button></div>}
        <div className="video-stage__modes">
          <button type="button" aria-pressed={theater} aria-label="Theater mode" onClick={toggleTheater}>THEATER</button>
          <button type="button" aria-pressed={fullscreen} aria-label="Fullscreen video" onClick={toggleFullscreen}>FULL</button>
        </div>
        {(theater || fullscreen) && <div className="video-stage__context" aria-label="Telemetry context">
          <span>{formatTime(time)}</span>
          <span>LAP {telemetryNumber(displayedCurrent?.lap_number) ?? "—"}</span>
          <span>{nextCornerName}</span>
        </div>}
        <button className="play-button" onClick={togglePlayback} aria-label="Play or pause">{playbackState === "playing" ? "Ⅱ" : "▶"}</button>
      </section>
      <aside className="track-panel"><div className="section-heading"><h2>Track</h2><span>OFFLINE ROUTE</span></div><Suspense fallback={<div className="track-map" role="status">Loading route map…</div>}><TrackMap samples={samples} current={displayedCurrent} ghost={ghost} corners={corners} track={session.edits.track} units={session.edits.display_units} /></Suspense>
        <div className="current-corner"><small>NEXT · {displayDistance(telemetryNumber(displayedCurrent?.lap_distance_m), session.edits.display_units)?.toFixed(0) ?? "—"} {distanceUnitLabel(session.edits.display_units).toUpperCase()}</small><strong>{telemetryNumber(displayedCurrent?.lap_distance_m) == null ? "—" : nextCornerName}</strong></div>
      </aside>
      <section className="plot-panel">
        <div className="section-heading">
          <h2>Telemetry</h2>
          <div className="chart-axis-mode" aria-label="Chart horizontal axis">
            <button type="button" aria-pressed={chartMode === "time"} onClick={() => setChartMode("time")}>TIME</button>
            <button type="button" aria-pressed={chartMode === "distance"} onClick={() => setChartMode("distance")}>DISTANCE</button>
          </div>
        </div>
        <TelemetryChart
          x={chartData.x}
          series={chartData.series}
          cursor={chartCursor}
          xLabel={chartMode === "time" ? "Time" : "Track distance"}
          xUnit={chartMode === "time" ? session.edits.display_units.time : distanceUnitLabel(session.edits.display_units)}
          speedUnit={speedUnitLabel(session.edits.display_units)}
          accelerationUnit={accelerationUnitLabel(session.edits.display_units)}
          interactive
          movingWindowSize={chartMode === "time" ? 20 : undefined}
          onHoverIndex={previewChartIndex}
          onSeekIndex={seekChartIndex}
        />
      </section>
      <Suspense fallback={<section className="lap-panel" aria-busy="true"><div className="section-heading"><h2>Laps</h2><span>Loading comparison…</span></div></section>}><LapPanel sessionId={sessionId} laps={laps} samples={samples} current={displayedCurrent} bookmarks={session.edits.bookmarks ?? []} preferredReferenceLap={session.edits.reference_lap} onSeek={seek} onPreviewTime={setChartPreviewTime} onGhostChange={setGhost} onReferenceLapChange={(lap) => void saveReferenceLap(lap)} onBookmarksChange={saveBookmarks} units={session.edits.display_units} /></Suspense>
    </ResizableReviewGrid>
    <footer className="player-bar"><button className="transport" aria-label={playbackState === "playing" ? "Pause" : playbackState === "ended" ? "Replay" : "Play"} onClick={togglePlayback}>{playbackState === "playing" ? "Ⅱ" : "▶"}</button><div className="step-controls"><button type="button" aria-label="Previous event" onClick={() => seekEvent(-1)}>│◀</button><button type="button" aria-label="Previous frame" onClick={() => seekFrame(-1)}>‹</button><button type="button" aria-label="Next frame" onClick={() => seekFrame(1)}>›</button><button type="button" aria-label="Next event" onClick={() => seekEvent(1)}>▶│</button></div><button className="mute-button" type="button" aria-label={muted ? "Unmute audio" : "Mute audio"} aria-pressed={muted} onClick={() => setMuted((value) => !value)}>{muted ? "MUTED" : "MUTE"}</button><Scrubber time={time} duration={session.duration_seconds} chapters={session.chapters} laps={laps} corners={corners} samples={samples} bookmarks={session.edits.bookmarks ?? []} onSeek={seek} />
      <select aria-label="Playback speed" value={playbackRate} onChange={(event) => { const rate = Number(event.target.value); if (video) video.playbackRate = rate; setPlaybackRate(rate); }}><option value="0.25">0.25×</option><option value="0.5">0.5×</option><option value="1">1×</option><option value="1.5">1.5×</option><option value="2">2×</option></select></footer>
  </main>;
}

export default function App() {
  const [sessions, setSessions] = useState<SessionManifest[]>([]);
  const [libraryError, setLibraryError] = useState("");
  const [libraryNotice, setLibraryNotice] = useState("");
  const [loadingLibrary, setLoadingLibrary] = useState(true);
  const [active, setActive] = useState<string | null>(() => new URLSearchParams(location.search).get("session"));
  const [importing, setImporting] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [pending, setPending] = useState<
    | { kind: "archive"; session: SessionManifest }
    | { kind: "delete"; session: SessionManifest }
    | { kind: "cleanup" }
    | null
  >(null);
  useEffect(() => {
    localStorage.setItem("race-review-units", JSON.stringify(storedDisplayUnits()));
  }, []);
  const refresh = (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoadingLibrary(true);
    setLibraryError("");
    return api.sessions()
      .then(setSessions)
      .catch((reason) => setLibraryError(errorMessage(reason, "Could not load the session library.")))
      .finally(() => setLoadingLibrary(false));
  };
  useEffect(() => { void refresh(); }, []);
  const open = (id: string) => { setActive(id); setImporting(false); history.replaceState(null, "", `?session=${id}`); };
  const runLibraryAction = async (id: string, action: () => Promise<void>) => {
    setBusyId(id);
    setLibraryError("");
    try {
      await action();
      await refresh({ silent: true });
    } catch (reason) {
      setLibraryError(errorMessage(reason, "The library action failed."));
    } finally {
      setBusyId(null);
      setPending(null);
    }
  };
  if (active) return <Review sessionId={active} onBack={() => { setActive(null); refresh(); history.replaceState(null, "", location.pathname); }} />;
  if (libraryError && !sessions.length && !importing) return <main className="loading"><ActionableError
    title="Could not load session library"
    message={libraryError}
    primaryAction={{ label: "Retry", onClick: () => void refresh(), disabled: loadingLibrary }}
    secondaryAction={{ label: "Start a new import", onClick: () => { setLibraryError(""); setImporting(true); } }}
  /></main>;
  if (loadingLibrary) return <main className="loading"><span role="status">Loading session library…</span></main>;
  if (importing || !sessions.length) return <ImportPanel onCreated={open} />;
  const activeSessions = sessions.filter((session) => session.status !== "archived");
  const archivedSessions = sessions.filter((session) => session.status === "archived");
  const renderCard = (session: SessionManifest, archived: boolean) => (
    <article key={session.session_id} className="session-card" data-archived={archived || undefined}>
      <button className="session-card__open" type="button" onClick={() => open(session.session_id)} disabled={archived}>
        <div className="session-card__image" style={{ backgroundImage: `url(/api/sessions/${session.session_id}/thumbnail)` }}><span>{session.status}</span></div>
        <div><strong>{session.name}</strong><small>{new Date(session.created_at).toLocaleDateString()} · {(session.duration_seconds / 60).toFixed(1)} min</small></div>
      </button>
      <div className="session-card__actions">
        {!archived && <button type="button" className="secondary" disabled={busyId != null} onClick={() => void runLibraryAction(session.session_id, () => api.exportBundle(session.session_id))}>Export</button>}
        {!archived && <button type="button" className="secondary" disabled={busyId != null} onClick={() => setPending({ kind: "archive", session })}>Archive</button>}
        {archived && <button type="button" className="secondary" disabled={busyId != null} onClick={() => void runLibraryAction(session.session_id, async () => { await api.restoreSession(session.session_id); })}>Restore</button>}
        {archived && <button type="button" className="secondary" disabled={busyId != null} onClick={() => setPending({ kind: "delete", session })}>Delete</button>}
      </div>
    </article>
  );
  return <main className="library">
    <header>
      <div className="wordmark"><span>GR86</span> / RACE REVIEW</div>
      <div className="library-actions">
        <button className="secondary" type="button" disabled={busyId != null} onClick={() => void runLibraryAction("backup", async () => {
          const backup = await api.backupCatalog();
          setLibraryNotice(`Catalog backup saved to ${backup.path}`);
        })}>Backup catalog</button>
        <button className="secondary" type="button" disabled={busyId != null} onClick={() => setPending({ kind: "cleanup" })}>Clean artifacts</button>
        <button className="primary" onClick={() => setImporting(true)}>New import</button>
      </div>
    </header>
    {libraryError && <ActionableError compact title="Library action failed" message={libraryError} primaryAction={{ label: "Dismiss", onClick: () => setLibraryError("") }} />}
    {libraryNotice && <p className="library-notice" role="status">{libraryNotice}</p>}
    <section>
      <p className="eyebrow">LOCAL SESSIONS</p>
      <h1>Race library</h1>
      <div className="session-grid">{activeSessions.map((session) => renderCard(session, false))}</div>
      {!activeSessions.length && <p className="muted">No active sessions. Restore an archived session or start a new import.</p>}
    </section>
    {!!archivedSessions.length && <section>
      <p className="eyebrow">ARCHIVED</p>
      <h2>Recoverable sessions</h2>
      <p className="muted">Archived sessions stay on disk until you confirm deletion by typing the session id.</p>
      <div className="session-grid">{archivedSessions.map((session) => renderCard(session, true))}</div>
    </section>}
    {pending?.kind === "archive" && <ConfirmDialog
      title="Archive session"
      confirmLabel="Archive"
      onCancel={() => setPending(null)}
      onConfirm={() => void runLibraryAction(pending.session.session_id, async () => { await api.archiveSession(pending.session.session_id); })}
      busy={busyId != null}
    >
      <p>Archive {pending.session.name}? You can restore it from the archived list. Analysis files stay on disk.</p>
    </ConfirmDialog>}
    {pending?.kind === "delete" && <ConfirmDialog
      title="Delete session"
      confirmLabel="Delete permanently"
      danger
      matchValue={pending.session.session_id}
      matchLabel="Type the session id to permanently delete it"
      onCancel={() => setPending(null)}
      onConfirm={() => void runLibraryAction(pending.session.session_id, async () => { await api.deleteSession(pending.session.session_id); })}
      busy={busyId != null}
    >
      <p>This permanently removes {pending.session.name} and its derived artifacts. Source GoPro files are not modified. Type {pending.session.session_id} to confirm.</p>
    </ConfirmDialog>}
    {pending?.kind === "cleanup" && <ConfirmDialog
      title="Clean artifacts"
      confirmLabel="Remove leftover files"
      onCancel={() => setPending(null)}
      onConfirm={() => void runLibraryAction("cleanup", async () => {
        const result = await api.cleanupArtifacts(false);
        setLibraryNotice(`Removed ${result.removed_paths.length} leftover path${result.removed_paths.length === 1 ? "" : "s"}.`);
      })}
      busy={busyId != null}
    >
      <p>Remove regenerable export copies and leftover partial transcodes from idle sessions. Running imports and sessions that need repair are skipped.</p>
    </ConfirmDialog>}
  </main>;
}
