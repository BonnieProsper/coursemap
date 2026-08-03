// Loads coursemap/api/static/app.js into a real jsdom window via an actual
// <script> tag, so it executes exactly as it does in a browser (including
// strict-mode top-level function declarations becoming window properties -
// this only works via a real script element, not a Node vm.runInThisContext
// call, which strict-mode scopes away from the global object).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { JSDOM } from "jsdom";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const APP_JS_PATH = path.join(__dirname, "..", "coursemap", "api", "static", "app.js");

/**
 * Create a jsdom window with app.js loaded and ready. Pass extra HTML to
 * `bodyHtml` for tests that exercise DOM-reading/writing functions - most
 * elements app.js's init() touches aren't present unless you add them here,
 * but that's fine for testing an individual function directly rather than
 * running the whole app.
 */
export function loadApp(bodyHtml = "") {
  // init() runs unconditionally when app.js loads (see below) and always
  // hits its "server offline" fallback here, since there's no real backend
  // to fetch from - it unconditionally touches these two elements on that
  // path, so they're always present, regardless of what an individual test
  // needs for the function it's actually exercising.
  const alwaysPresent = `
    <div id="freshness-badge"><span id="freshness-text"></span></div>
  `;
  const dom = new JSDOM(
    `<!DOCTYPE html><html><body>${alwaysPresent}${bodyHtml}</body></html>`,
    { url: "http://localhost/", runScripts: "dangerously" }
  );
  // app.js calls init() unconditionally at the bottom of the file (this is
  // a real browser script, not a module with an opt-in entry point). init()
  // calls initTheme(), which uses matchMedia - not implemented by jsdom.
  // Stubbed here so loading the script doesn't throw; the fetch calls
  // init() goes on to make will simply reject (no server running in this
  // test context), which is expected and doesn't affect a directly-called
  // function under test.
  dom.window.matchMedia = dom.window.matchMedia || (() => ({
    matches: false,
    addListener() {}, removeListener() {},
    addEventListener() {}, removeEventListener() {},
  }));
  const script = dom.window.document.createElement("script");
  script.textContent = readFileSync(APP_JS_PATH, "utf-8");
  dom.window.document.body.appendChild(script);
  return dom;
}
