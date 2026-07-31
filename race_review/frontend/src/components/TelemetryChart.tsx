import { useEffect, useId, useRef, useState } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";

type Series = { label: string; values: Array<number | null>; color: string; scale?: string };
type InteractionMode = "inspect" | "zoom" | "pan" | "select";

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

function clampWindow(minimum: number, maximum: number, fullMinimum: number, fullMaximum: number) {
  const span = Math.min(maximum - minimum, fullMaximum - fullMinimum);
  let nextMinimum = minimum;
  if (nextMinimum < fullMinimum) nextMinimum = fullMinimum;
  if (nextMinimum + span > fullMaximum) nextMinimum = fullMaximum - span;
  return [nextMinimum, nextMinimum + span] as const;
}

export function TelemetryChart({
  x,
  series,
  cursor,
  xLabel = "Distance m",
  xUnit = "m",
  speedUnit = "mph",
  accelerationUnit = "g",
  interactive = false,
  movingWindowSize,
  onHoverIndex,
  onSeekIndex,
}: {
  x: number[];
  series: Series[];
  cursor?: number;
  xLabel?: string;
  xUnit?: string;
  speedUnit?: string;
  accelerationUnit?: string;
  interactive?: boolean;
  movingWindowSize?: number;
  onHoverIndex?: (index: number | null) => void;
  onSeekIndex?: (index: number) => void;
}) {
  const element = useRef<HTMLDivElement>(null);
  const plot = useRef<uPlot | null>(null);
  const interactionRef = useRef<InteractionMode>("inspect");
  const onHoverIndexRef = useRef(onHoverIndex);
  const onSeekIndexRef = useRef(onSeekIndex);
  const [interaction, setInteraction] = useState<InteractionMode>("inspect");
  const [movingWindow, setMovingWindow] = useState(false);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);
  const [selectedRange, setSelectedRange] = useState<[number, number] | null>(null);
  const [visibleRange, setVisibleRange] = useState<[number, number] | null>(null);
  const summaryId = useId();
  const readoutIndex = cursor == null || !x.length ? null : nearestIndex(x, cursor);
  const displayedIndex = selectedIndex ?? readoutIndex;

  useEffect(() => { interactionRef.current = interaction; }, [interaction]);
  useEffect(() => { onHoverIndexRef.current = onHoverIndex; }, [onHoverIndex]);
  useEffect(() => { onSeekIndexRef.current = onSeekIndex; }, [onSeekIndex]);

  useEffect(() => {
    if (!element.current || !x.length) return;
    const fullRange: [number, number] = [x[0], x[x.length - 1]];
    let dragStart: { pixel: number; value: number; range: [number, number] } | null = null;
    const chart = new uPlot(
      {
        width: element.current.clientWidth,
        height: element.current.clientHeight || 180,
        legend: { show: false },
        cursor: { drag: { x: false, y: false } },
        axes: [
          { stroke: "#6f7b80", grid: { stroke: "#242b2e" }, label: `${xLabel} (${xUnit})` },
          { scale: series[0]?.scale, side: 3, stroke: "#b9c1c4", grid: { stroke: "#242b2e" }, label: series[0]?.scale === "speed" ? `Speed (${speedUnit})` : undefined },
          ...(series.some((item) => item.scale === "acceleration") ? [{ scale: "acceleration", side: 1 as const, stroke: "#ff725f", grid: { show: false }, label: `Acceleration (${accelerationUnit})` }] : []),
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
    setVisibleRange(fullRange);

    const indexAt = (event: MouseEvent) => {
      const bounds = chart.over.getBoundingClientRect();
      const pixel = Math.max(0, Math.min(bounds.width, event.clientX - bounds.left));
      return {
        index: nearestIndex(x, chart.posToVal(pixel, "x")),
        pixel,
        bounds,
      };
    };
    const handlePointerMove = (event: PointerEvent) => {
      const { index, pixel, bounds } = indexAt(event);
      onHoverIndexRef.current?.(index);
      if (!dragStart || interactionRef.current !== "pan") return;
      const span = dragStart.range[1] - dragStart.range[0];
      const delta = ((dragStart.pixel - pixel) / Math.max(1, bounds.width)) * span;
      const [minimum, maximum] = clampWindow(
        dragStart.range[0] + delta,
        dragStart.range[1] + delta,
        fullRange[0],
        fullRange[1],
      );
      chart.setScale("x", { min: minimum, max: maximum });
      setVisibleRange([minimum, maximum]);
    };
    const handlePointerDown = (event: PointerEvent) => {
      if (event.button !== 0) return;
      const { pixel, index } = indexAt(event);
      const scale = chart.scales.x;
      dragStart = {
        pixel,
        value: x[index],
        range: [scale.min ?? fullRange[0], scale.max ?? fullRange[1]],
      };
      chart.over.setPointerCapture(event.pointerId);
    };
    const handlePointerUp = (event: PointerEvent) => {
      if (!dragStart) return;
      const start = dragStart;
      const { pixel, index } = indexAt(event);
      const movement = Math.abs(pixel - start.pixel);
      if (movement < 4 || interactionRef.current === "inspect") {
        setSelectedIndex(index);
        setSelectedRange(null);
        onSeekIndexRef.current?.(index);
      } else if (interactionRef.current === "zoom") {
        const end = x[index];
        const [minimum, maximum] = start.value < end ? [start.value, end] : [end, start.value];
        if (maximum > minimum) {
          chart.setScale("x", { min: minimum, max: maximum });
          setVisibleRange([minimum, maximum]);
        }
      } else if (interactionRef.current === "select") {
        const end = x[index];
        setSelectedRange(start.value < end ? [start.value, end] : [end, start.value]);
        setSelectedIndex(index);
        onSeekIndexRef.current?.(index);
      }
      dragStart = null;
      if (chart.over.hasPointerCapture(event.pointerId)) chart.over.releasePointerCapture(event.pointerId);
    };
    const handlePointerLeave = () => {
      if (!dragStart) onHoverIndexRef.current?.(null);
    };
    const handleClick = (event: MouseEvent) => {
      if (interactionRef.current !== "inspect") return;
      const { index } = indexAt(event);
      setSelectedIndex(index);
      setSelectedRange(null);
      onSeekIndexRef.current?.(index);
    };
    const handleWheel = (event: WheelEvent) => {
      if (!interactive) return;
      event.preventDefault();
      setMovingWindow(false);
      const { index } = indexAt(event);
      const center = x[index];
      const scale = chart.scales.x;
      const minimum = scale.min ?? fullRange[0];
      const maximum = scale.max ?? fullRange[1];
      const factor = event.deltaY < 0 ? 0.8 : 1.25;
      const [nextMinimum, nextMaximum] = clampWindow(
        center - (center - minimum) * factor,
        center + (maximum - center) * factor,
        fullRange[0],
        fullRange[1],
      );
      chart.setScale("x", { min: nextMinimum, max: nextMaximum });
      setVisibleRange([nextMinimum, nextMaximum]);
    };
    chart.over.addEventListener("pointermove", handlePointerMove);
    element.current.addEventListener("pointerdown", handlePointerDown, true);
    element.current.addEventListener("pointerup", handlePointerUp, true);
    chart.over.addEventListener("pointerleave", handlePointerLeave);
    chart.over.addEventListener("click", handleClick);
    chart.over.addEventListener("wheel", handleWheel, { passive: false });
    const resize = new ResizeObserver((entries) => {
      const width = Math.max(1, Math.floor(entries[0]?.contentRect.width ?? 400));
      const height = Math.max(1, Math.floor(entries[0]?.contentRect.height || 180));
      if (chart.width !== width || chart.height !== height) chart.setSize({ width, height });
    });
    resize.observe(element.current);
    return () => {
      resize.disconnect();
      chart.over.removeEventListener("pointermove", handlePointerMove);
      element.current?.removeEventListener("pointerdown", handlePointerDown, true);
      element.current?.removeEventListener("pointerup", handlePointerUp, true);
      chart.over.removeEventListener("pointerleave", handlePointerLeave);
      chart.over.removeEventListener("click", handleClick);
      chart.over.removeEventListener("wheel", handleWheel);
      plot.current = null;
      chart.destroy();
    };
  }, [accelerationUnit, interactive, series, speedUnit, x, xLabel, xUnit]);

  useEffect(() => {
    const chart = plot.current;
    if (!chart || cursor == null) return;
    const minimum = chart.scales.x.min ?? x[0];
    const maximum = chart.scales.x.max ?? x[x.length - 1];
    const left = maximum > minimum
      ? ((cursor - minimum) / (maximum - minimum)) * chart.over.clientWidth
      : 0;
    chart.setCursor({
      left,
      top: Math.max(1, chart.over.clientHeight / 2),
    });
    chart.root.querySelector(".u-cursor-x")?.classList.toggle("u-off", cursor <= x[0]);
    if (movingWindow && movingWindowSize && x.length) {
      const [minimum, maximum] = clampWindow(
        cursor - movingWindowSize / 2,
        cursor + movingWindowSize / 2,
        x[0],
        x[x.length - 1],
      );
      chart.setScale("x", { min: minimum, max: maximum });
      setVisibleRange([minimum, maximum]);
    }
  }, [cursor, movingWindow, movingWindowSize, x]);

  const reset = () => {
    if (!plot.current || !x.length) return;
    interactionRef.current = "inspect";
    setInteraction("inspect");
    setMovingWindow(false);
    setSelectedRange(null);
    setSelectedIndex(null);
    setVisibleRange([x[0], x[x.length - 1]]);
    plot.current.setScale("x", { min: x[0], max: x[x.length - 1] });
  };
  const setMode = (mode: InteractionMode) => {
    interactionRef.current = mode;
    setMovingWindow(false);
    setInteraction(mode);
  };
  const windowMinimum = visibleRange?.[0] ?? x[0];
  const windowMaximum = visibleRange?.[1] ?? x[x.length - 1];
  const pointSummary = displayedIndex == null
    ? "No point selected."
    : `Point at ${formatValue(x[displayedIndex])} ${xUnit}. ${series.map((item) => `${item.label} ${formatValue(item.values[displayedIndex])}`).join(", ")}.`;

  return <div
    className="telemetry-chart"
    data-scales={Array.from(new Set(series.map((item) => item.scale).filter(Boolean))).join(" ")}
    data-interaction={interaction}
    data-moving-window={movingWindow}
    data-interactive={interactive}
  >
    {interactive && <div className="telemetry-chart__toolbar" aria-label="Chart controls">
      {(["inspect", "zoom", "pan", "select"] as const).map((mode) => <button
        key={mode}
        type="button"
        aria-pressed={interaction === mode}
        onClick={() => setMode(mode)}
      >{mode.toUpperCase()}</button>)}
      {movingWindowSize && <button
        type="button"
        aria-pressed={movingWindow}
        onClick={() => setMovingWindow((value) => !value)}
      >{movingWindowSize}S WINDOW</button>}
      <button type="button" onClick={reset}>RESET</button>
    </div>}
    <div className="telemetry-chart__readout" aria-label="Telemetry chart legend">
      <span>{xLabel}{cursor == null ? "" : ` · ${formatValue(cursor)} ${xUnit}`}</span>
      {series.map((item) => <span key={item.label} data-scale={item.scale}><i style={{ background: item.color }} />{item.label}{readoutIndex == null ? "" : ` ${formatValue(item.values[readoutIndex])}`}</span>)}
    </div>
    <div
      className="telemetry-chart__plot"
      ref={element}
      role="img"
      aria-label={`${xLabel} telemetry plot`}
      aria-describedby={summaryId}
    />
    <p className="visually-hidden" id={summaryId} role="status" aria-label="Chart window summary">
      Window {formatValue(windowMinimum)} to {formatValue(windowMaximum)} {xUnit}. {pointSummary}
      {selectedRange ? ` Selected range ${formatValue(selectedRange[0])} to ${formatValue(selectedRange[1])} ${xUnit}.` : ""}
    </p>
  </div>;
}
