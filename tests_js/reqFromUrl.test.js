import { describe, it, expect } from "vitest";
import { loadApp } from "./loadApp.js";

describe("_reqFromUrl", () => {
  it("applies documented defaults when the query string is empty", () => {
    const { window } = loadApp();
    const p = new window.URLSearchParams("");
    const req = window._reqFromUrl(p);
    expect(req.major).toBe("");
    expect(req.double_major).toBeNull();
    expect(req.start_semester).toBe("S1");
    expect(req.max_credits).toBe(60);
    expect(req.campus).toBe("D");
    expect(req.mode).toBe("DIS");
    expect(req.no_summer).toBe(false);
    expect(req.auto_fill).toBe(false);
    expect(req.transfer_credits).toBe(0);
    expect(req.completed).toEqual([]);
    expect(req.prefer).toEqual([]);
    expect(req.exclude).toEqual([]);
  });

  it("reads every field from a fully-populated share link", () => {
    const { window } = loadApp();
    const qs =
      "major=Computer+Science&dm=Mathematics&year=2027&sem=S2&cr=45" +
      "&campus=A&mode=INT&nosummer=1&fill=1&transfer=60" +
      "&done=159201,159234&prefer=159261&exclude=159301,159302";
    const req = window._reqFromUrl(new window.URLSearchParams(qs));
    expect(req).toEqual({
      major: "Computer Science",
      double_major: "Mathematics",
      start_year: 2027,
      start_semester: "S2",
      max_credits: 45,
      campus: "A",
      mode: "INT",
      no_summer: true,
      auto_fill: true,
      transfer_credits: 60,
      completed: ["159201", "159234"],
      prefer: ["159261"],
      exclude: ["159301", "159302"],
    });
  });

  it("falls back to the default rather than NaN for a non-numeric year/credits value", () => {
    const { window } = loadApp();
    const req = window._reqFromUrl(new window.URLSearchParams("year=notanumber&cr=notanumber"));
    expect(req.start_year).toBe(new Date().getFullYear());
    expect(req.max_credits).toBe(60);
  });

  it("drops empty entries from a trailing/leading comma in a code list", () => {
    const { window } = loadApp();
    const req = window._reqFromUrl(new window.URLSearchParams("done=,159201,,159234,"));
    expect(req.completed).toEqual(["159201", "159234"]);
  });
});
