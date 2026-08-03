import { describe, it, expect } from "vitest";
import { loadApp } from "./loadApp.js";

describe("extractMinorCodes", () => {
  it("collects a single COURSE node's code", () => {
    const { window } = loadApp();
    const minor = { requirement: { type: "COURSE", course_code: "159201" } };
    expect(window.extractMinorCodes(minor)).toEqual(["159201"]);
  });

  it("walks nested children and dedupes repeated codes", () => {
    const { window } = loadApp();
    const minor = {
      requirement: {
        type: "ALL_OF",
        children: [
          { type: "COURSE", course_code: "159201" },
          { type: "COURSE", course_code: "159234" },
          { type: "COURSE", course_code: "159201" },
        ],
      },
    };
    expect(window.extractMinorCodes(minor)).toEqual(["159201", "159234"]);
  });

  it("takes only the first 4 codes from a pool's course_codes list", () => {
    const { window } = loadApp();
    const minor = {
      requirement: {
        type: "ANY_OF",
        course_codes: ["A1", "A2", "A3", "A4", "A5", "A6"],
      },
    };
    expect(window.extractMinorCodes(minor)).toEqual(["A1", "A2", "A3", "A4"]);
  });

  it("returns an empty array for a minor with no requirement tree", () => {
    const { window } = loadApp();
    expect(window.extractMinorCodes({})).toEqual([]);
  });
});
