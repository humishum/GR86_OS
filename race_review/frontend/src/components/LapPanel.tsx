import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import type { LapSummary } from "../types";
import { formatTime } from "../telemetry";
import { DEFAULT_DISPLAY_UNITS, displayDistance, displaySpeed, distanceUnitLabel, speedUnitLabel } from "../displayUnits";
import type { DisplayUnits } from "../types";
import { ActionableError, errorMessage } from "./ActionableError";
import { TelemetryChart } from "./TelemetryChart";

export function LapPanel({ sessionId, laps, onSeek, units = DEFAULT_DISPLAY_UNITS }: { sessionId: string; laps: LapSummary[]; onSeek: (value: number) => void; units?: DisplayUnits }) {
  const completeLaps = useMemo(() => laps.filter((lap) => lap.complete && !lap.excluded), [laps]);
  const [reference, setReference] = useState(completeLaps[0]?.lap_number ?? 1);
  const [comparison, setComparison] = useState(completeLaps[1]?.lap_number ?? 2);
  const [data, setData] = useState<Record<string, number[]> | null>(null);
  const [comparisonError, setComparisonError] = useState("");
  const [comparisonRequest, setComparisonRequest] = useState(0);
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
  const chartSeries = useMemo(() => data ? [
    { label: `Lap ${reference} ${speedUnitLabel(units)}`, values: data.reference_speed_mps.map((value) => displaySpeed(value, units)), color: "#f2f5f6" },
    { label: `Lap ${comparison} ${speedUnitLabel(units)}`, values: data.comparison_speed_mps.map((value) => displaySpeed(value, units)), color: "#ff5038" },
  ] : [], [data, reference, comparison, units]);
  return (
    <section className="lap-panel">
      <div className="section-heading"><h2>Laps</h2><span>{completeLaps.length} complete</span></div>
      <div className="lap-table" role="table">
        {laps.map((lap) => (
          <button key={lap.lap_number} className="lap-row" onClick={() => onSeek(lap.start_seconds)}>
            <strong>{lap.complete ? lap.lap_number : "—"}</strong><span>{formatTime(lap.lap_time_seconds)}{lap.complete ? "" : " partial"}</span>
            <span>{displaySpeed(lap.maximum_speed_mps, units)?.toFixed(0) ?? "—"} {speedUnitLabel(units)}</span>
          </button>
        ))}
      </div>
      {completeLaps.length >= 2 && <div className="comparison">
        <div className="comparison__controls">
          <label>Reference <select value={reference} onChange={(event) => setReference(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
          <label>Compare <select value={comparison} onChange={(event) => setComparison(Number(event.target.value))}>{completeLaps.map((lap) => <option key={lap.lap_number}>{lap.lap_number}</option>)}</select></label>
        </div>
        {comparisonError && <ActionableError
          compact
          title="Could not load lap comparison"
          message={comparisonError}
          primaryAction={{ label: "Retry comparison", onClick: () => setComparisonRequest((value) => value + 1) }}
        />}
        {data && <><TelemetryChart x={data.distance_m.map((value) => displayDistance(value, units) ?? 0)} series={chartSeries} xLabel="Distance" xUnit={distanceUnitLabel(units)} speedUnit={speedUnitLabel(units)} /><TelemetryChart x={data.distance_m.map((value) => displayDistance(value, units) ?? 0)} series={[{ label: "Delta s", values: data.delta_s, color: "#ffb238" }]} xLabel="Distance" xUnit={distanceUnitLabel(units)} /></>}
      </div>}
    </section>
  );
}
