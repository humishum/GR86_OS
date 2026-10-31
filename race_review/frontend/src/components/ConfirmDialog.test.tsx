import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ConfirmDialog } from "./ConfirmDialog";

describe("ConfirmDialog", () => {
  it("keeps a typed-id delete action disabled until the session id matches", () => {
    const onConfirm = vi.fn();
    render(
      <ConfirmDialog
        title="Delete session"
        confirmLabel="Delete permanently"
        danger
        matchValue="sess-123abc"
        matchLabel="Type the session id to permanently delete it"
        onConfirm={onConfirm}
        onCancel={() => undefined}
      >
        <p>Type the id to confirm.</p>
      </ConfirmDialog>,
    );

    const confirm = screen.getByRole("button", { name: "Delete permanently" });
    const field = screen.getByLabelText("Type the session id to permanently delete it");
    expect(confirm).toBeDisabled();
    fireEvent.change(field, { target: { value: "sess-123ab" } });
    expect(confirm).toBeDisabled();
    fireEvent.change(field, { target: { value: "sess-123abc" } });
    expect(confirm).toBeEnabled();
    fireEvent.click(confirm);
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });
});
