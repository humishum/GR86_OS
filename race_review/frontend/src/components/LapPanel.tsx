import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { sampleAtLapDistance, videoTimeAtDistance } from "../comparison";
import type { Bookmark, DisplayUnits, LapComparison, LapSummary } from "../types";
import { formatTime, telemetryNumber, type TelemetrySample } from "../telemetry";
import { DEFAULT_DISPLAY_UNITS, displayDistance, displaySpeed, distanceUnitLabel, speedUnitLabel } from "../displayUnits";
import { ActionableError, errorMessage } from "./ActionableError";
import { ReviewNotes } from "./ReviewNotes";
import { TelemetryChart } from "./TelemetryChart";

function formatDelta(value: number) {
  return `${value > 0 ? "+" : ""}${value.toFixed(2)} s`;
}

function speedReadout(value: number | null | undefined, units: DisplayUnits) {
  const displayed = displaySpeed(value, units);
  return displayed == null ? "—" : displayed.toFixed(0);
}

export function LapPanel({
  sessionId,
  laps,
  samples,
  current,
  bookmarks,
  preferredReferenceLap,
  units = DEFAULT_DISPLAY_UNITS,
  onSeek,
  onPreviewTime,
  onGhostChange,
  onReferenceLapChange,
  onBookmarksChange,
}: {
  sessionId: string;
  laps: LapSummary[];
  samples: TelemetrySample[];
  current: TelemetrySample | null;
  bookmarks: Bookmark[];
  preferredReferenceLap?: number | null;
  units?: DisplayUnits;
  onSeek: (value: number) => void;
  onPreviewTime: (value: number | null) => void;
  onGhostChange: (value: TelemetrySample | null) => void;
  onReferenceLapChange: (value: number) => void;
  onBookmarksChange: (value: Bookmark[]) => Promise<void> | void;
}) {
  const completeLaps = useMemo(() => laps.filter((lap) => lap.complete && !lap.excluded), [laps]);
  const defaultReference = completeLaps.some((lap) => lap.lap_number === preferredReferenceLap)
    ? preferredReferenceLap as number
    : completeLaps[0]?.lap_number ?? 1;
  const defaultComparison = completeLaps.find((lap) => lap.lap_number !== defaultReference)?.lap_number
    ?? completeLaps[1]?.lap_number
    ?? 2;
  const [reference, setReference] = useState(defaultReference);
  const [comparison, setComparison] = useState(defaultComparison);
  const [data, setData] = useState<LapComparison | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonRequest, setComparisonRequest] = useState(0);
  const [hoverDistance, setHoverDistance] = useState<number | null>(null);

  useEffect(() => {
    if (!completeLaps.some((lap) => lap.lap_number === reference)) setReference(defaultReference);
  }, [completeLaps, defaultReference, reference]);
  useEffect(() => {
    if (preferredReferenceLap != null && completeLaps.some((lap) => lap.lap_number === preferredReferenceLap)) {
      setReference(preferredReferenceLap);
    }
  }, [completeLaps, preferredReferenceLap]);

  useEffect(() => {
    let active = true;
    setData(null);
    setComparisonError("");
    if (reference === comparison || completeLaps.length < 2) return;
    void api.comparison(sessionId, reference, comparison)
      .then((value) => { if (active) setData(value); })
      .catch((reason) => {
        if (active) setComparisonError(errorMessage(reason, "Could not load the lap comparison."));
      });
    return () => { active = false; };
  }, [sessionId, reference, comparison, completeLaps.length, comparisonRequest]);

  const currentLap = telemetryNumber(current?.lap_number);
  const liveDistance = currentLap === reference || currentLap === comparison
    ? telemetryNumber(current?.lap_distance_m)
    : null;
  const cursorDistance = hoverDistance ?? liveDistance;
  const displayedCursor = cursorDistance == null ? undefined : displayDistance(cursorDistance, units) ?? undefined;
  const chartSeries = useMemo(() => data ? [
    { label: `Lap ${reference} ${speedUnitLabel(units)}`, values: data.reference_speed_mps.map((value) => displaySpeed(value, units)), color: "#f2f5f6" },
    { label: `Lap ${comparison} ${speedUnitLabel(units)}`, values: data.comparison_speed_mps.map((value) => displaySpeed(value, units)), color: "#ff5038" },
  ] : [], [data, reference, comparison, units]);
  const regions = data?.regions ?? [];
  const cornerCards = data?.corners ?? [];
  const ghostLap = currentLap === reference ? comparison : reference;

  useEffect(() => {
    if (cursorDistance == null) {
      onGhostChange(null);
      return;
    }
    onGhostChange(sampleAtLapDistance(samples, ghostLap, cursorDistance));
  }, [cursorDistance, ghostLap, onGhostChange, samples]);

  const seekDistance = (distance: number) => {
    if (!data) return;
    const time = videoTimeAtDistance({
      distance,
      distances: data.distance_m,
      referenceTime: data.reference_time_s,
      comparisonTime: data.comparison_time_s,
      referenceLap: reference,
      comparisonLap: comparison,
      currentLap,
      laps,
    });
    if (time != null) onSeek(time);
  };
  const previewIndex = (index: number | null) => {
    if (index == null || !data) {
      setHoverDistance(null);
      onPreviewTime(null);
      return;
    }
    const distance = data.distance_m[index];
    setHoverDistance(distance);
    onPreviewTime(videoTimeAtDistance({
      distance,
      distances: data.distance_m,
      referenceTime: data.reference_time_s,
      comparisonTime: data.comparison_time_s,
      referenceLap: reference,
      comparisonLap: comparison,
      currentLap,
      laps,
    }));
  };
  const seekIndex = (index: number) => {
    if (!data) return;
    seekDistance(data.distance_m[index]);
  };
  const selectReference = (value: number) => {
    setReference(value);
    if (value === comparison) {
      const other = completeLaps.find((lap) => lap.lap_number !== value);
      if (other) setComparison(other.lap_number);
    }
    onReferenceLapChange(value);
  };

  return (
    <section className="lap-panel">
      <div className="section-heading"><h2>Laps</h2><span>{completeLaps.length} complete</span></div>
      <div className="lap-table" role="table">
        {laps.map((lap) => (
          <button
            key={lap.lap_number}
            className={`lap-row${lap.lap_number === reference ? " lap-row--reference" : ""}${lap.lap_number === comparison ? " lap-row--comparison" : ""}`}
            onClick={() => onSeek(lap.start_seconds)}
          >
            <strong>{lap.complete ? lap.lap_number : "—"}</strong><span>{formatTime(lap.lap_time_seconds)}{lap.complete ? "" : " partial"}</span>
            <span>{displaySpeed(lap.maximum_speed_mps, units)?.toFixed(0) ?? "—"} {speedUnitLabel(units)}</span>
          </button>
        ))}
      </div>
      {completeLaps.length >= 2 && <div className="comparison">
        <div className="comparison__controls">
          <label>Reference <select value={reference} onChange={(event) => selectReference(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
          <label>Compare <select value={comparison} onChange={(event) => setComparison(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
        </div>
        {comparisonError && <ActionableError
          compact
          title="Could not load lap comparison"
          message={comparisonError}
          primaryAction={{ label: "Retry comparison", onClick: () => setComparisonRequest((value) => value + 1) }}
        />}
        {data && <>
          <TelemetryChart
            x={data.distance_m.map((value) => displayDistance(value, units) ?? 0)}
            series={chartSeries}
            cursor={displayedCursor}
            xLabel="Distance"
            xUnit={distanceUnitLabel(units)}
            speedUnit={speedUnitLabel(units)}
            onHoverIndex={previewIndex}
            onSeekIndex={seekIndex}
          />
          <TelemetryChart
            x={data.distance_m.map((value) => displayDistance(value, units) ?? 0)}
            series={[{ label: "Delta s", values: data.delta_s, color: "#ffb238" }]}
            cursor={displayedCursor}
            xLabel="Distance"
            xUnit={distanceUnitLabel(units)}
            onHoverIndex={previewIndex}
            onSeekIndex={seekIndex}
          />
        </>}
        {!!regions.length && <div className="comparison-regions" aria-label="Largest gain and loss regions">
          <div className="section-heading"><h3>Largest deltas</h3></div>
          {regions.map((region) => (
            <button
              key={`${region.kind}-${region.start_distance_m}-${region.end_distance_m}`}
              type="button"
              className={`delta-region delta-region--${region.kind}`}
              onClick={() => seekDistance(region.start_distance_m)}
            >
              <strong>{region.kind === "gain" ? "GAIN" : "LOSS"}</strong>
              <span>{displayDistance(region.start_distance_m, units)?.toFixed(0) ?? "—"}–{displayDistance(region.end_distance_m, units)?.toFixed(0) ?? "—"} {distanceUnitLabel(units)}</span>
              <span>{formatDelta(region.delta_change_s)}</span>
            </button>
          ))}
        </div>}
        {!!cornerCards.length && <div className="corner-cards" aria-label="Corner comparison ranked by time impact">
          <div className="section-heading"><h3>Corners by time</h3></div>
          {cornerCards.map((corner) => (
            <button
              key={corner.corner_id}
              type="button"
              className="corner-card"
              onClick={() => seekDistance(corner.start_distance_m)}
            >
              <div className="corner-card__title">
                <strong>{corner.name}</strong>
                <span data-kind={corner.time_impact_s <= 0 ? "gain" : "loss"}>{formatDelta(corner.time_impact_s)}</span>
              </div>
              <dl>
                <div><dt>Entry</dt><dd>{speedReadout(corner.reference_entry_speed_mps, units)} / {speedReadout(corner.comparison_entry_speed_mps, units)}</dd></div>
                <div><dt>Apex</dt><dd>{speedReadout(corner.reference_apex_speed_mps, units)} / {speedReadout(corner.comparison_apex_speed_mps, units)}</dd></div>
                <div><dt>Exit</dt><dd>{speedReadout(corner.reference_exit_speed_mps, units)} / {speedReadout(corner.comparison_exit_speed_mps, units)}</dd></div>
                <div><dt>Lat peak</dt><dd>{corner.reference_peak_lateral_g?.toFixed(2) ?? "—"} / {corner.comparison_peak_lateral_g?.toFixed(2) ?? "—"}</dd></div>
                <div><dt>Brake</dt><dd>{displayDistance(corner.reference_braking_distance_m, units)?.toFixed(0) ?? "—"} / {displayDistance(corner.comparison_braking_distance_m, units)?.toFixed(0) ?? "—"} {distanceUnitLabel(units)}</dd></div>
              </dl>
            </button>
          ))}
        </div>}
        {data && cursorDistance != null && <p className="visually-hidden" role="status">
          Comparison cursor at {displayDistance(cursorDistance, units)?.toFixed(0) ?? "—"} {distanceUnitLabel(units)}.
          Ghost lap {ghostLap} is {sampleAtLapDistance(samples, ghostLap, cursorDistance) ? "linked" : "unavailable"}.
        </p>}
      </div>}
      <ReviewNotes
        bookmarks={bookmarks}
        time={telemetryNumber(current?.timestamp) ?? 0}
        onSeek={onSeek}
        onSave={onBookmarksChange}
      />
    </section>
  );
}
