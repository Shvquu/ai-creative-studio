#!/usr/bin/env node
// Dashboard smoke test (Playwright, headless Chromium).
//
// Usage:  node e2e/smoke.mjs [baseUrl] [--screens <dir>] [--no-generate]
// Default baseUrl: http://127.0.0.1:8420  (the backend serves the built dashboard)
//
// Opens every section, asserts the main heading, checks for console/page errors,
// generates one image with the mock provider (no AI model needed) and verifies the
// result appears in the Asset Library. Exits with code 1 on any failure.

import { createRequire } from "node:module";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const args = process.argv.slice(2);
const base = (args.find((a) => /^https?:\/\//.test(a)) ?? "http://127.0.0.1:8420").replace(/\/$/, "");
const screensIdx = args.indexOf("--screens");
const screens = screensIdx >= 0 ? args[screensIdx + 1] : null;
const generate = !args.includes("--no-generate");
if (screens) mkdirSync(screens, { recursive: true });

const SECTIONS = [
  ["dashboard", "Dashboard"],
  ["images", "Image Studio"],
  ["videos", "Video Studio"],
  ["brand", "Brand Studio"],
  ["workflows", "Workflow Studio"],
  ["assets", "Asset Library"],
  ["settings", "Settings"],
];

const failures = [];
const fail = (msg) => {
  failures.push(msg);
  console.error(`  ✗ ${msg}`);
};
const ok = (msg) => console.log(`  ✓ ${msg}`);

const browser = await chromium.launch();
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 1 });
  const page = await context.newPage();
  const errors = [];
  page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));

  console.log(`Dashboard smoke test against ${base}`);
  for (const [id, heading] of SECTIONS) {
    errors.length = 0;
    await page.goto(`${base}/#/${id}`, { waitUntil: "networkidle" });
    try {
      await page.getByRole("heading", { level: 1, name: heading }).waitFor({ timeout: 10000 });
      ok(`${id}: Überschrift "${heading}"`);
    } catch {
      fail(`${id}: Überschrift "${heading}" nicht gefunden`);
    }
    await page.waitForTimeout(800);
    if (errors.length) fail(`${id}: ${errors.join(" | ")}`);
    if (screens) await page.screenshot({ path: join(screens, `${id}.png`), fullPage: true });
  }

  // Dashboard content
  await page.goto(`${base}/#/dashboard`, { waitUntil: "networkidle" });
  try {
    await page.getByText("Hardwareprofil").waitFor({ timeout: 15000 });
    ok("dashboard: Systemstatus geladen");
  } catch {
    fail("dashboard: Systemstatus fehlt");
  }

  // Image generation with the mock provider
  if (generate) {
    await page.goto(`${base}/#/images`, { waitUntil: "networkidle" });
    await page.getByLabel("Prompt", { exact: true }).fill("e2e smoke test – a paper boat on a pond");
    await page.getByLabel("Provider").selectOption("mock");
    await page.getByRole("button", { name: "Generieren", exact: true }).click();
    try {
      await page.locator(".job-result .thumb img").first().waitFor({ timeout: 60000 });
      ok("images: Mock-Bild generiert und angezeigt");
    } catch {
      fail("images: Generiertes Bild erscheint nicht");
    }
    if (screens) await page.screenshot({ path: join(screens, "images-result.png"), fullPage: true });
  }

  // Cost confirmation flow (HTTP 402 → dialog → resend with confirm_token), simulated via request interception
  {
    await page.goto(`${base}/#/images`, { waitUntil: "networkidle" });
    let secondBody = null;
    let calls = 0;
    await page.route("**/api/images/generate", async (route) => {
      calls += 1;
      if (calls === 1) {
        await route.fulfill({
          status: 402,
          contentType: "application/json",
          body: JSON.stringify({
            error: {
              code: "cost_confirmation_required",
              message: "Diese Aktion kostet ca. 0.08 USD (e2e-cloud, 2×).",
              details: {
                estimate: {
                  provider: "e2e-cloud", location: "cloud", operation: "image.generate", model: "test", count: 2,
                  unit_cost: 0.04, total_cost: 0.08, currency: "USD", is_free: false, requires_confirmation: true,
                  confirmation_token: "tok123", budget_monthly: 5, budget_spent: 0, budget_remaining: 5,
                  resources: { vram_gb: null, ram_gb: null, est_seconds: 10, disk_mb: 3, note: "Cloud" },
                },
              },
            },
          }),
        });
      } else {
        secondBody = route.request().postDataJSON();
        await route.continue({ postData: JSON.stringify({ ...secondBody, provider: "mock", confirm_token: undefined }) });
      }
    });
    await page.getByLabel("Prompt", { exact: true }).fill("e2e cost dialog");
    await page.getByLabel("Provider").selectOption("mock");
    await page.getByRole("button", { name: "Generieren", exact: true }).click();
    try {
      await page.getByRole("dialog", { name: "Kostenpflichtige Aktion bestätigen" }).waitFor({ timeout: 5000 });
      if (screens) await page.screenshot({ path: join(screens, "cost-dialog.png") });
      await page.getByRole("button", { name: "Kosten akzeptieren und ausführen" }).click();
      await page.waitForTimeout(1500);
      if (secondBody?.confirm_token === "tok123") ok("Kostenbestätigung: Dialog + erneuter Request mit confirm_token");
      else fail(`Kostenbestätigung: zweiter Request ohne Token (${JSON.stringify(secondBody)})`);
    } catch {
      fail("Kostenbestätigung: Dialog erscheint nicht");
    }
    await page.unroute("**/api/images/generate");
  }

  // Asset library → detail drawer
  await page.goto(`${base}/#/assets`, { waitUntil: "networkidle" });
  const thumbs = page.locator(".grid-assets .thumb");
  await thumbs.first().waitFor({ timeout: 15000 }).catch(() => undefined);
  if ((await thumbs.count()) > 0) {
    ok(`assets: ${await thumbs.count()} Assets sichtbar`);
    await thumbs.first().click();
    try {
      await page.locator(".drawer .preview").waitFor({ timeout: 10000 });
      ok("assets: Detail-Drawer mit Vorschau");
      if (screens) await page.screenshot({ path: join(screens, "assets-detail.png") });
    } catch {
      fail("assets: Detail-Drawer öffnet nicht");
    }
    await page.keyboard.press("Escape");
  } else fail("assets: keine Assets sichtbar");

  // Workflow form
  await page.goto(`${base}/#/workflows`, { waitUntil: "networkidle" });
  const card = page.locator(".wf-card").first();
  await card.waitFor({ timeout: 15000 }).catch(() => undefined);
  if (await card.count()) {
    await card.click();
    try {
      await page.getByRole("button", { name: "Workflow starten" }).waitFor({ timeout: 5000 });
      ok("workflows: dynamisches Formular");
      if (screens) await page.screenshot({ path: join(screens, "workflows-form.png"), fullPage: true });
    } catch {
      fail("workflows: Formular fehlt");
    }
  } else fail("workflows: keine Workflows gelistet");

  // Settings tabs
  await page.goto(`${base}/#/settings`, { waitUntil: "networkidle" });
  await page.getByRole("tab", { name: "Modelle" }).click();
  try {
    await page.locator(".table tbody tr").first().waitFor({ timeout: 10000 });
    ok("settings: Modellkatalog");
    if (screens) await page.screenshot({ path: join(screens, "settings-models.png"), fullPage: true });
  } catch {
    fail("settings: Modellkatalog fehlt");
  }
  await page.getByRole("tab", { name: "Provider" }).click();
  try {
    await page.locator(".switch").first().waitFor({ timeout: 10000 });
    ok("settings: Provider-Liste");
    if (screens) await page.screenshot({ path: join(screens, "settings-providers.png"), fullPage: true });
  } catch {
    fail("settings: Provider-Liste fehlt");
  }

  // Theme toggle
  await page.getByRole("button", { name: "Farbschema wechseln" }).click();
  const theme = await page.evaluate(() => document.documentElement.dataset.theme);
  if (theme === "light") ok("Theme-Umschaltung");
  else fail(`Theme-Umschaltung: ${theme}`);
  if (screens) {
    await page.goto(`${base}/#/dashboard`, { waitUntil: "networkidle" });
    await page.waitForTimeout(500);
    await page.screenshot({ path: join(screens, "dashboard-light.png"), fullPage: true });
  }
  await page.getByRole("button", { name: "Farbschema wechseln" }).click();

  // Mobile layout
  const mobile = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 1, isMobile: true, hasTouch: true });
  const m = await mobile.newPage();
  const mErrors = [];
  m.on("pageerror", (e) => mErrors.push(e.message));
  await m.goto(`${base}/#/dashboard`, { waitUntil: "networkidle" });
  await m.waitForTimeout(800);
  const overflow = await m.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  if (overflow > 1) fail(`mobile: horizontaler Überlauf ${overflow}px`);
  else ok("mobile: kein horizontaler Überlauf");
  if (mErrors.length) fail(`mobile: ${mErrors.join(" | ")}`);
  if (screens) {
    await m.screenshot({ path: join(screens, "mobile-dashboard.png"), fullPage: true });
    await m.goto(`${base}/#/images`, { waitUntil: "networkidle" });
    await m.waitForTimeout(500);
    await m.screenshot({ path: join(screens, "mobile-images.png"), fullPage: false });
  }
} finally {
  await browser.close();
}

if (failures.length) {
  console.error(`\n${failures.length} Fehler`);
  process.exit(1);
}
console.log("\nAlle Prüfungen bestanden.");
