import { useState } from "react";
import type { TelemetrySample } from "../telemetry";
import { mph, telemetryNumber } from "../telemetry";

function Gauge({ label, value, unit, accent }: { label: string; value: string; unit: string; accent?: boolean }) {
  return (
    <div className={`gauge ${accent ? "gauge--accent" : ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
      <small>{unit}</small>
    </div>
  );
}

function GForceWidget({ lateral, longitudinal }: { lateral: number | null; longitudinal: number | null }) {
  const [showVector, setShowVector] = useState(true);
  const hasVector = lateral != null && longitudinal != null;
  const limit = Math.max(1.25, Math.abs(lateral ?? 0), Math.abs(longitudinal ?? 0));
  const x = hasVector ? 50 + (lateral / limit) * 42 : 50;
  // Positive longitudinal acceleration points up; braking points down.
  const y = hasVector ? 50 - (longitudinal / limit) * 42 : 50;
  return <div className={`g-force-widget ${showVector ? "g-force-widget--vector" : "g-force-widget--values"}`} aria-label="G-force meter">
    <button type="button" aria-label="Toggle G-force display" aria-pressed={showVector} onClick={() => setShowVector((value) => !value)}>
      <span>G FORCE</span><small>{showVector ? "VECTOR" : "VALUES"}</small>
    </button>
    {showVector ? <div className="g-force-widget__plot" aria-label={hasVector ? `Lateral ${lateral.toFixed(2)} g, longitudinal ${longitudinal.toFixed(2)} g` : "G-force unavailable"}>
      <i className="g-force-widget__ring g-force-widget__ring--inner" />
      <i className="g-force-widget__ring" />
      <i className="g-force-widget__axis g-force-widget__axis--x" />
      <i className="g-force-widget__axis g-force-widget__axis--y" />
      {hasVector && <i className="g-force-widget__dot" style={{ left: `${x}%`, top: `${y}%` }} />}
      <small className="g-force-widget__limit">±{limit.toFixed(2)}g</small>
    </div> : <div className="g-force-widget__readout">
      <span>LAT <strong>{lateral == null ? "—" : lateral.toFixed(2)}</strong></span>
      <span>LONG <strong>{longitudinal == null ? "—" : longitudinal.toFixed(2)}</strong></span>
    </div>}
  </div>;
}

export function Gauges({ sample, delta }: { sample: TelemetrySample | null; delta: number | null }) {
  const speed = mph(telemetryNumber(sample?.speed_mps));
  const longitudinal = telemetryNumber(sample?.longitudinal_g);
  const lateral = telemetryNumber(sample?.lateral_g);
  const lap = telemetryNumber(sample?.lap_number);
  return (
    <div className="gauges" aria-label="Live telemetry">
      <Gauge label="SPEED" value={speed == null ? "—" : speed.toFixed(0)} unit="MPH" accent />
      <GForceWidget longitudinal={longitudinal} lateral={lateral} />
      <Gauge label="LAP" value={lap == null ? "—" : String(Math.round(lap))} unit="CURRENT" />
      <Gauge label="DELTA" value={delta == null ? "—" : `${delta >= 0 ? "+" : ""}${delta.toFixed(2)}`} unit="SEC" />
    </div>
  );
}
