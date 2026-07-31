import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Gauges } from "./Gauges";

function gaugeValue(label: string) {
  const gauge = screen.getByText(label).closest<HTMLElement>(".gauge");
  if (!gauge) throw new Error(`Gauge ${label} was not rendered`);
  return within(gauge).getByText(/^(?:—|[+-]?\d+(?:\.\d+)?)$/);
}

describe("Gauges", () => {
  it("renders unavailable telemetry as em dashes, never synthetic zeroes", () => {
    render(<Gauges sample={null} delta={null} />);

    expect(gaugeValue("SPEED")).toHaveTextContent("—");
    expect(gaugeValue("LAP")).toHaveTextContent("—");
    expect(gaugeValue("DELTA")).toHaveTextContent("—");
    expect(screen.getByLabelText("G-force unavailable")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Toggle G-force display" }));
    const gForces = screen.getByLabelText("G-force meter");
    expect(within(gForces).getByText("LAT").querySelector("strong")).toHaveTextContent("—");
    expect(within(gForces).getByText("LONG").querySelector("strong")).toHaveTextContent("—");
    expect(within(gForces).queryByText(/^0(?:\.0+)?$/)).not.toBeInTheDocument();
  });

  it("keeps legitimate zero readings distinct from missing readings", () => {
    render(<Gauges
      sample={{ speed_mps: 0, lateral_g: 0, longitudinal_g: 0, lap_number: 0 }}
      delta={0}
    />);

    expect(gaugeValue("SPEED")).toHaveTextContent("0");
    expect(gaugeValue("LAP")).toHaveTextContent("0");
    expect(gaugeValue("DELTA")).toHaveTextContent("+0.00");
    expect(screen.getByLabelText("Lateral 0.00 g, longitudinal 0.00 g")).toBeInTheDocument();
  });

  it("renders persisted metric speed and acceleration units", () => {
    render(<Gauges
      sample={{ speed_mps: 25, lateral_g: 1, longitudinal_g: -1, lap_number: 1 }}
      delta={null}
      units={{ speed: "km/h", acceleration: "m/s²", distance: "m", time: "s" }}
    />);

    expect(gaugeValue("SPEED")).toHaveTextContent("90");
    expect(screen.getByText("KM/H")).toBeInTheDocument();
    expect(screen.getByLabelText("Lateral 9.81 m/s², longitudinal -9.81 m/s²")).toBeInTheDocument();
  });
});
