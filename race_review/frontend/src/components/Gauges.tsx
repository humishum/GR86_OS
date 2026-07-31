import { useState } from "react";
import type { TelemetrySample } from "../telemetry";
import { telemetryNumber } from "../telemetry";
import { accelerationUnitLabel, DEFAULT_DISPLAY_UNITS, displayAcceleration, displaySpeed, speedUnitLabel } from "../displayUnits";
import type { DisplayUnits } from "../types";

function Gauge({ label, value, unit, accent }: { label: string; value: string; unit: string; accent?: boolean }) {
  return (
    <div className={`gauge ${accent ? "gauge--accent" : ""} ${value.length > 4 ? "gauge--compact-value" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{unit}</small>
    </div>
  );
}

function GForceWidget({ lateral, longitudinal, unit }: { lateral: number | null; longitudinal: number | null; unit: string }) {
  const [showVector, setShowVector] = useState(true);
  const hasVector = lateral != null && longitudinal != null;
  const limit = Math.max(1.25, Math.abs(lateral ?? 0), Math.abs(longitudinal ?? 0));
  const x = hasVector ? 50 + (lateral / limit) * 42 : 50;
  // Positive longitudinal acceleration points up; braking points down.
  const y = hasVector ? 50 - (longitudinal / limit) * 42 : 50;
  return <div className={`g-force-widget ${showVector ? "g-force-widget--vector" : "g-force-widget--values"}`} aria-label="G-force meter">
    <button type="button" aria-label="Toggle G-force display" aria-pressed={showVector} onClick={() => setShowVector((value) => !value)}>
      <span className="visually-hidden">G force · {showVector ? "vector" : "values"}</span>
      {showVector ? <div className="g-force-widget__plot" aria-label={hasVector ? `Lateral ${lateral.toFixed(2)} ${unit}, longitudinal ${longitudinal.toFixed(2)} ${unit}` : "G-force unavailable"}>
      <i className="g-force-widget__ring" />
      <i className="g-force-widget__axis g-force-widget__axis--x" />
      <i className="g-force-widget__axis g-force-widget__axis--y" />
      {hasVector && <i className="g-force-widget__dot" style={{ left: `${x}%`, top: `${y}%` }} />}
    </div> : <div className="g-force-widget__readout">
      <span>LAT <strong>{lateral == null ? "—" : lateral.toFixed(2)}</strong></span>
      <span>LONG <strong>{longitudinal == null ? "—" : longitudinal.toFixed(2)}</strong></span>
    </div>}
    </button>
  </div>;
}

export function Gauges({ sample, delta, units = DEFAULT_DISPLAY_UNITS }: { sample: TelemetrySample | null; delta: number | null; units?: DisplayUnits }) {
  const speed = displaySpeed(telemetryNumber(sample?.speed_mps), units);
  const longitudinal = displayAcceleration(telemetryNumber(sample?.longitudinal_g), units);
  const lateral = displayAcceleration(telemetryNumber(sample?.lateral_g), units);
  const lap = telemetryNumber(sample?.lap_number);
  return (
    <div className="gauges" aria-label="Live telemetry">
      <Gauge label="SPEED" value={speed == null ? "—" : speed.toFixed(0)} unit={speedUnitLabel(units).toUpperCase()} accent />
      <GForceWidget longitudinal={longitudinal} lateral={lateral} unit={accelerationUnitLabel(units)} />
      <Gauge label="LAP" value={lap == null ? "—" : String(Math.round(lap))} unit="CURRENT" />
      <Gauge label="DELTA" value={delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`} unit="SEC" />
    </div>
  );
}
