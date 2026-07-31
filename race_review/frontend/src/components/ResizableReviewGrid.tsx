import { Children, useCallback, useRef, useState, type CSSProperties, type KeyboardEvent, type PointerEvent, type ReactNode, type RefObject } from "react";

type Split = "column" | "leftRow" | "rightRow";

const DEFAULT_COLUMN = 73;
const DEFAULT_ROW = 72;

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value));
}

export function ResizableReviewGrid({ children }: { children: ReactNode }) {
  const panels = Children.toArray(children);
  const grid = useRef<HTMLDivElement>(null);
  const leftColumn = useRef<HTMLDivElement>(null);
  const rightColumn = useRef<HTMLDivElement>(null);
  const [column, setColumn] = useState(DEFAULT_COLUMN);
  const [leftRow, setLeftRow] = useState(DEFAULT_ROW);
  const [rightRow, setRightRow] = useState(DEFAULT_ROW);

  const resizeAt = useCallback((split: Split, clientPosition: number) => {
    const target: RefObject<HTMLDivElement | null> = split === "column" ? grid : split === "leftRow" ? leftColumn : rightColumn;
    const bounds = target.current?.getBoundingClientRect();
    if (!bounds) return;
    if (split === "column") setColumn(clamp(((clientPosition - bounds.left) / bounds.width) * 100, 35, 80));
    else {
      const value = clamp(((clientPosition - bounds.top) / bounds.height) * 100, 25, 85);
      if (split === "leftRow") setLeftRow(value); else setRightRow(value);
    }
  }, []);

  const pointerDown = (split: Split) => (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    resizeAt(split, split === "column" ? event.clientX : event.clientY);
  };
  const pointerMove = (split: Split) => (event: PointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) resizeAt(split, split === "column" ? event.clientX : event.clientY);
  };
  const keyDown = (split: Split) => (event: KeyboardEvent<HTMLDivElement>) => {
    const isColumn = split === "column";
    const decrease = isColumn ? event.key === "ArrowLeft" : event.key === "ArrowUp";
    const increase = isColumn ? event.key === "ArrowRight" : event.key === "ArrowDown";
    if (!decrease && !increase && event.key !== "Home") return;
    event.preventDefault();
    if (event.key === "Home") {
      if (isColumn) setColumn(DEFAULT_COLUMN);
      else if (split === "leftRow") setLeftRow(DEFAULT_ROW);
      else setRightRow(DEFAULT_ROW);
      return;
    }
    const update = (value: number) => clamp(value + (increase ? 2 : -2), isColumn ? 35 : 25, isColumn ? 80 : 85);
    if (isColumn) setColumn(update);
    else if (split === "leftRow") setLeftRow(update);
    else setRightRow(update);
  };

  const style = {
    "--review-column": `${column}%`,
    "--review-left-row": `${leftRow}%`,
    "--review-right-row": `${rightRow}%`,
  } as CSSProperties;

  const rowSplitter = (split: "leftRow" | "rightRow", value: number, label: string) => <div
    className="review-grid__splitter review-grid__splitter--row"
    role="separator"
    aria-label={label}
    aria-orientation="horizontal"
    aria-valuemin={25}
    aria-valuemax={85}
    aria-valuenow={Math.round(value)}
    tabIndex={0}
    onPointerDown={pointerDown(split)}
    onPointerMove={pointerMove(split)}
    onKeyDown={keyDown(split)}
    onDoubleClick={() => split === "leftRow" ? setLeftRow(DEFAULT_ROW) : setRightRow(DEFAULT_ROW)}
  />;

  return <div className="review-grid" ref={grid} style={style}>
    <div className="review-grid__column review-grid__column--left" ref={leftColumn}>
      {panels[0]}
      {panels[2]}
      {rowSplitter("leftRow", leftRow, "Resize video and telemetry panels")}
    </div>
    <div className="review-grid__column review-grid__column--right" ref={rightColumn}>
      {panels[1]}
      {panels[3]}
      {rowSplitter("rightRow", rightRow, "Resize track and lap panels")}
    </div>
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
      onDoubleClick={() => setColumn(DEFAULT_COLUMN)}
    />
  </div>;
}
