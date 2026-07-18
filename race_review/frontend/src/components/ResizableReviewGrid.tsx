import { useCallback, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode } from "react";

type Axis = "column" | "row";

const DEFAULT_COLUMN = 73;
const DEFAULT_ROW = 72;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function ResizableReviewGrid({ children }: { children: ReactNode }) {
  const grid = useRef<HTMLDivElement>(null);
  const [column, setColumn] = useState(DEFAULT_COLUMN);
  const [row, setRow] = useState(DEFAULT_ROW);

  const resizeAt = useCallback((axis: Axis, clientPosition: number) => {
    const bounds = grid.current?.getBoundingClientRect();
    if (!bounds) return;
    if (axis === "column") setColumn(clamp(((clientPosition - bounds.left) / bounds.width) * 100, 35, 80));
    else setRow(clamp(((clientPosition - bounds.top) / bounds.height) * 100, 35, 80));
  }, []);

  const pointerDown = (axis: Axis) => (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeAt(axis, axis === "column" ? event.clientX : event.clientY);
  };
  const pointerMove = (axis: Axis) => (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeAt(axis, axis === "column" ? event.clientX : event.clientY);
  };
  const keyDown = (axis: Axis) => (event: KeyboardEvent<HTMLDivElement>) => {
    const decrease = axis === "column" ? event.key === "ArrowLeft" : event.key === "ArrowUp";
    const increase = axis === "column" ? event.key === "ArrowRight" : event.key === "ArrowDown";
    if (!decrease && !increase && event.key !== "Home") return;
    event.preventDefault();
    if (event.key === "Home") {
      if (axis === "column") setColumn(DEFAULT_COLUMN); else setRow(DEFAULT_ROW);
      return;
    }
    const update = (value: number) => clamp(value + (increase ? 2 : -2), 35, 80);
    if (axis === "column") setColumn(update); else setRow(update);
  };
  const reset = (axis: Axis) => () => {
    if (axis === "column") setColumn(DEFAULT_COLUMN); else setRow(DEFAULT_ROW);
  };

  const style = {
    "--review-column": `${column}%`,
    "--review-row": `${row}%`,
  } as CSSProperties;

  return <div className="review-grid" ref={grid} style={style}>
    {children}
    <div
      className="review-grid__splitter review-grid__splitter--column"
      role="separator"
      aria-label="Resize track and video panels"
      aria-orientation="vertical"
      aria-valuemin={35}
      aria-valuemax={80}
      aria-valuenow={Math.round(column)}
      tabIndex={0}
      onPointerDown={pointerDown("column")}
      onPointerMove={pointerMove("column")}
      onKeyDown={keyDown("column")}
      onDoubleClick={reset("column")}
    />
    <div
      className="review-grid__splitter review-grid__splitter--row"
      role="separator"
      aria-label="Resize video and telemetry panels"
      aria-orientation="horizontal"
      aria-valuemin={35}
      aria-valuemax={80}
      aria-valuenow={Math.round(row)}
      tabIndex={0}
      onPointerDown={pointerDown("row")}
      onPointerMove={pointerMove("row")}
      onKeyDown={keyDown("row")}
      onDoubleClick={reset("row")}
    />
  </div>;
}
