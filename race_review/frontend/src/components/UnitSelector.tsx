import type { DisplayUnits } from "../types";

type Props = {
  value: DisplayUnits;
  onChange: (value: DisplayUnits) => void;
};

export function UnitSelector({ value, onChange }: Props) {
  const update = <Key extends keyof DisplayUnits>(key: Key, next: DisplayUnits[Key]) => {
    onChange({ ...value, [key]: next });
  };

  return <div className="coordinate-row" aria-label="Display units">
    <label>Speed<select value={value.speed} onChange={(event) => update("speed", event.target.value as DisplayUnits["speed"])}>
      <option value="mph">mph</option><option value="km/h">km/h</option>
    </select></label>
    <label>Acceleration<select value={value.acceleration} onChange={(event) => update("acceleration", event.target.value as DisplayUnits["acceleration"])}>
      <option value="g">g</option><option value="m/s²">m/s²</option>
    </select></label>
    <label>Distance<select value={value.distance} onChange={(event) => update("distance", event.target.value as DisplayUnits["distance"])}>
      <option value="ft">ft</option><option value="m">m</option>
    </select></label>
  </div>;
}
