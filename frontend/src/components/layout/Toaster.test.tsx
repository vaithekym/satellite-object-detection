import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TOAST_DURATION_MS, toast, useToasts } from "../../store/toasts";
import Toaster from "./Toaster";

describe("Toaster", () => {
  afterEach(() => {
    useToasts.setState({ toasts: [] });
    vi.useRealTimers();
  });

  it("shows toasts, errors as alerts, and lets the user dismiss them", () => {
    render(<Toaster />);
    act(() => {
      toast.success("naip.tif er lastet opp og klar.");
      toast.error("Analyse feilet: model crashed");
    });
    expect(screen.getByRole("status")).toHaveTextContent("naip.tif er lastet opp og klar.");
    expect(screen.getByRole("alert")).toHaveTextContent("Analyse feilet: model crashed");

    fireEvent.click(screen.getAllByRole("button", { name: "Lukk varsel" })[0]);
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });

  it("removes toasts automatically", () => {
    vi.useFakeTimers();
    render(<Toaster />);
    act(() => toast.info("Analysen er lagt i kø."));
    expect(screen.getByText("Analysen er lagt i kø.")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(TOAST_DURATION_MS + 10));
    expect(screen.queryByText("Analysen er lagt i kø.")).not.toBeInTheDocument();
  });
});
