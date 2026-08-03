import { describe, it, expect, beforeEach } from "vitest";
import { loadApp } from "./loadApp.js";

describe("getSaved / setSaved", () => {
  it("returns an empty array when nothing has been saved yet", () => {
    const { window } = loadApp();
    expect(window.getSaved()).toEqual([]);
  });

  it("round-trips a list of saved plans through localStorage", () => {
    const { window } = loadApp();
    const plans = [
      { name: "Plan A", req: { major: "Computer Science" } },
      { name: "Plan B", req: { major: "Mathematics" } },
    ];
    window.setSaved(plans);
    expect(window.getSaved()).toEqual(plans);
  });

  it("survives a second load of app.js against the same localStorage (page refresh)", () => {
    const first = loadApp();
    first.window.setSaved([{ name: "Persisted", req: {} }]);
    const stored = first.window.localStorage.getItem("cm_saved_plans");

    const second = loadApp();
    second.window.localStorage.setItem("cm_saved_plans", stored);
    expect(second.window.getSaved()).toEqual([{ name: "Persisted", req: {} }]);
  });

  it("returns an empty array instead of throwing when localStorage holds invalid JSON", () => {
    const { window } = loadApp();
    window.localStorage.setItem("cm_saved_plans", "{not valid json");
    expect(window.getSaved()).toEqual([]);
  });
});
