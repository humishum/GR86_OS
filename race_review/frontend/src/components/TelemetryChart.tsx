import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

type Series = { label: string; values: Array<number | null>; color: string; scale?: string };

function accelerationRange(_plot: uPlot, minimum: number, maximum: number): [number, number] {
  const magnitude = Math.max(1, Math.abs(minimum), Math.abs(maximum));
  const padded = Math.ceil(magnitude * 1.1 * 4) / 4;
  return [-padded, padded];
}

function nearestIndex(values: number[], target: number) {
  let low = 0;
  let high = values.length - 1;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (values[middle] < target) low = middle + 1;
    else high = middle;
  }
  if (low > 0 && Math.abs(values[low - 1] - target) < Math.abs(values[low] - target)) return low - 1;
  return low;
}

function formatValue(value: number | null | undefined) {
  if (value == null || !Number.isFinite(value)) return "—";
  const absolute = Math.abs(value);
  if (absolute >= 100) return value.toFixed(0);
  if (absolute >= 10) return value.toFixed(1);
  return value.toFixed(2);
}

export function TelemetryChart({
  x,
  series,
  cursor,
  xLabel = "Distance m",
}: {
  x: number[];
  series: Series[];
  cursor?: number;
  xLabel?: string;
}) {
  const element = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const readoutIndex = cursor == null || !x.length ? null : nearestIndex(x, cursor);
  useEffect(() => {
    if (!element.current || !x.length) return;
    const chart = new uPlot(
      {
        width: element.current.clientWidth,
        height: element.current.clientHeight || 180,
        legend: { show: false },
        cursor: { drag: { x: false, y: false } },
        axes: [
          { stroke: "#6f7b80", grid: { stroke: "#242b2e" } },
          { scale: series[0]?.scale, side: 3, stroke: "#b9c1c4", grid: { stroke: "#242b2e" }, label: series[0]?.scale === "speed" ? "Speed (mph)" : undefined },
          ...(series.some((item) => item.scale === "acceleration") ? [{ scale: "acceleration", side: 1 as const, stroke: "#ff725f", grid: { show: false }, label: "Acceleration (g)" }] : []),
        ],
        scales: {
          x: { time: false },
          ...(series.some((item) => item.scale === "speed") ? { speed: { range: (_plot: uPlot, minimum: number, maximum: number) => [Math.min(0, minimum), maximum * 1.05] as [number, number] } } : {}),
          ...(series.some((item) => item.scale === "acceleration") ? { acceleration: { range: accelerationRange } } : {}),
        },
        series: [
          { label: xLabel },
          ...series.map((item) => ({ label: item.label, stroke: item.color, width: 2, scale: item.scale })),
        ],
      },
      [x, ...series.map((item) => item.values)] as uPlot.AlignedData,
      element.current,
    );
    plot.current = chart;
    const resize = new ResizeObserver(() => chart.setSize({ width: element.current?.clientWidth ?? 400, height: element.current?.clientHeight || 180 }));
    resize.observe(element.current);
    return () => { resize.disconnect(); plot.current = null; chart.destroy(); };
  }, [x, series, xLabel]);
  useEffect(() => {
    if (plot.current && cursor != null) plot.current.setCursor({ left: plot.current.valToPos(cursor, "x"), top: 0 });
  }, [cursor]);
  return <div className="telemetry-chart" data-scales={Array.from(new Set(series.map((item) => item.scale).filter(Boolean))).join(" ")}>
    <div className="telemetry-chart__readout" aria-label="Telemetry chart legend">
      <span>{xLabel}{cursor == null ? "" : ` · ${cursor.toFixed(3)} s`}</span>
      {series.map((item) => <span key={item.label} data-scale={item.scale}><i style={{ background: item.color }} />{item.label}{readoutIndex == null ? "" : ` ${formatValue(item.values[readoutIndex])}`}</span>)}
    </div>
    <div className="telemetry-chart__plot" ref={element} />
  </div>;
}
