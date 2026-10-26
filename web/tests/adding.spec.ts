// The "Adding your prayers to Google Calendar..." tab that Finish opens.
// It's opened with window.opener set, so here a test pretends the setup tab opened it.
//
// The mock API's week preview (POST /api/calendar/preview) starts on Monday
// Oct 26, 2026: Fajr 6:10, Dhuhr 1:00, Asr 3:30, Maghrib 6:00, Isha 7:30. With
// finishedSettings(), Dhuhr and Isha are at KMA on weekdays, each with a drive
// block from 19 to 5 minutes before. The clock is faked, so "a block every
// second" is checked exactly.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";
import type { Settings } from "../src/types";

async function openAdding(page: Page, { path = "/adding?colour=7", settings = finishedSettings() as Settings, api = new MockApi() } = {}) {
  await api.signedIn(settings).install(page);
  await page.clock.install();
  // Like being opened by the setup tab, so the page waits instead of saying "Nothing to add here".
  await page.addInitScript(() => Object.defineProperty(window, "opener", { value: window, writable: true }));
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Adding your prayers to Google Calendar...");
  return api;
}

const caption = (page: Page) => page.locator(".adding-caption");
const blocks = (page: Page) => page.locator(".week-block");

test("the heading and the line under it", async ({ page }) => {
  await openAdding(page);
  await expect(page.locator(".adding-wait")).toHaveText("This can take up to a minute.");
});

for (const width of [320, 390, 412, 768, 1280, 1680]) {
  test(`it fills the screen, with "This can take up to a minute." on one line, at ${width}px wide`, async ({ page }) => {
    const height = width < 760 ? 844 : 800;
    await page.setViewportSize({ width, height });
    await openAdding(page);
    await page.clock.runFor(3000);
    const line = await page.locator(".adding-wait").evaluate((el) => {
      const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
      return el.getBoundingClientRect().height < lineHeight * 1.5 && el.scrollWidth <= el.clientWidth + 1;
    });
    expect(line).toBe(true);
    // Nothing wider than the screen, and the week fills most of it without running off the bottom.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    const week = (await page.locator(".week").boundingBox())!;
    expect(week.height).toBeGreaterThan(height * 0.45);
    expect(week.y + week.height).toBeLessThanOrEqual(height + 1);
    // Big text: the heading is at least 2rem, and bigger than the line under it.
    const [heading, wait] = await Promise.all(
      ["main h1", ".adding-wait"].map((s) => page.locator(s).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))),
    );
    expect(heading).toBeGreaterThanOrEqual(32);
    expect(heading).toBeGreaterThan(wait);
  });
}

test("a week view: 7 days across and times down the side", async ({ page }) => {
  await openAdding(page);
  await page.clock.runFor(1000);
  await expect(page.locator(".week-day")).toHaveText(["Mon26", "Tue27", "Wed28", "Thu29", "Fri30", "Sat31", "Sun1"]);
  // From the hour before Fajr (6:10) to the hour after Isha ends (7:40).
  await expect(page.locator(".week-hour").first()).toHaveText("6 AM");
  await expect(page.locator(".week-hour").last()).toHaveText("8 PM");
  // Hidden from screen readers. The heading says what's happening.
  await expect(page.locator(".week")).toHaveAttribute("aria-hidden", "true");
});

test("each day fills in from Fajr to Isha, one block a second, with a caption", async ({ page }) => {
  await openAdding(page);
  await expect(blocks(page)).toHaveCount(0);
  await page.clock.runFor(1000);
  await expect(blocks(page)).toHaveCount(1);
  await expect(caption(page)).toHaveText("Adding Monday's Fajr");
  await page.clock.runFor(1000);
  // The drive slides in just before the masjid prayer.
  await expect(caption(page)).toHaveText("Adding Monday's drive to KMA");
  await page.clock.runFor(1000);
  await expect(caption(page)).toHaveText("Adding Monday's Dhuhr at KMA");
  await expect(blocks(page)).toHaveCount(3);
  // Monday is the day being filled in.
  await expect(page.locator(".week-day.now")).toHaveText("Mon26");
  await page.clock.runFor(4000);
  await expect(caption(page)).toHaveText("Adding Monday's Isha at KMA");
  await page.clock.runFor(1000);
  await expect(caption(page)).toHaveText("Adding Tuesday's Fajr");
  await expect(page.locator(".week-day.now")).toHaveText("Tue27");
});

test("each block sits at its real time of day", async ({ page }) => {
  await openAdding(page);
  await page.clock.runFor(1000);
  const [fajr, six, seven] = await Promise.all([
    blocks(page).first().boundingBox(),
    page.locator(".week-hour", { hasText: /^6 AM$/ }).boundingBox(),
    page.locator(".week-hour", { hasText: /^7 AM$/ }).boundingBox(),
  ]);
  // Fajr at 6:10: a sixth of the way from the 6 AM line to the 7 AM line.
  const expected = six!.y + (seven!.y - six!.y) / 6;
  expect(Math.abs(fajr!.y - expected)).toBeLessThan(2);
});

test("prayer blocks use the prayer colour, and drive blocks the drive colour and their own animation", async ({ page }) => {
  await openAdding(page);
  await page.clock.runFor(3000);
  const look = (selector: string) =>
    page.locator(selector).first().evaluate((el) => {
      const s = getComputedStyle(el);
      return { colour: s.backgroundColor, animation: s.animationName };
    });
  // Peacock (#039be5), the saved prayer colour.
  expect(await look(".week-block.prayer")).toEqual({ colour: "rgb(3, 155, 229)", animation: "prayer-in" });
  // No drive colour saved, so the app's dark green.
  expect(await look(".week-block.drive")).toEqual({ colour: "rgb(15, 74, 45)", animation: "drive-in" });
});

test("after the whole week, it starts again", async ({ page }) => {
  await openAdding(page);
  // 7 days of 5 prayers, plus a drive before Dhuhr and Isha on the 5 weekdays: 45 blocks.
  await page.clock.runFor(45_000);
  await expect(blocks(page)).toHaveCount(45);
  await expect(caption(page)).toHaveText("Adding Sunday's Isha");
  await page.clock.runFor(1000);
  await expect(caption(page)).toHaveText("Your week is in");
  await page.clock.runFor(3000);
  await expect(blocks(page)).toHaveCount(0);
  await page.clock.runFor(1000);
  await expect(caption(page)).toHaveText("Adding Monday's Fajr");
});

test("it asks again while setup is still saving, then uses the real times", async ({ page }) => {
  const api = new MockApi();
  api.previewNotReady = 2;
  await openAdding(page, { api });
  for (let asked = 1; asked <= 3; asked++) {
    await api.sent("POST", "/api/calendar/preview", asked);
    await page.clock.runFor(1300);
  }
  await page.clock.runFor(3000);
  await expect(page.locator(".week-block.drive")).not.toHaveCount(0);
});

test("if the times never come, a typical week fills in instead", async ({ page }) => {
  const api = new MockApi();
  api.previewNotReady = 99;
  await openAdding(page, { api });
  // It asks 6 times, 1.2 seconds apart. Each answer comes back for real, so step the clock one wait at a time.
  for (let asked = 1; asked <= 6; asked++) {
    await api.sent("POST", "/api/calendar/preview", asked);
    await page.clock.runFor(1300);
  }
  await page.clock.runFor(3000);
  await expect(blocks(page)).not.toHaveCount(0);
  // A typical week has no drive blocks.
  await expect(page.locator(".week-block.drive")).toHaveCount(0);
});

test("a colour that isn't one of Google's uses the app's green", async ({ page }) => {
  await openAdding(page, { path: "/adding?colour=red", settings: { ...finishedSettings(), prayer_color_id: null } });
  await page.clock.runFor(1000);
  expect(await blocks(page).first().evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(23, 102, 63)");
});

test("with motion turned off, a spinner shows instead", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  const api = await openAdding(page);
  await expect(page.locator(".spinner")).toBeVisible();
  await expect(page.locator(".week")).toHaveCount(0);
  expect(api.calls("POST", "/api/calendar/preview")).toHaveLength(0);
});

test("the prayer colour picked in setup reaches the new tab", async ({ page }) => {
  const api = new MockApi().signedIn();
  // Slow enough that the tab is still on the Adding page when it's checked.
  api.finishDelayMs = 1500;
  await api.install(page);
  await page.goto("/");
  await page.getByRole("combobox", { name: "Address" }).pressSequentially("200 Kanata", { delay: 20 });
  await page.getByRole("option", { name: /^200 Kanata Avenue, Ottawa/ }).click();
  // The location is saved once the masjid search opens up.
  await expect(page.getByRole("combobox", { name: "Masjid" })).toBeEnabled();
  await page.getByRole("button", { name: "I pray at home" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  await page.getByRole("option", { name: "Grape" }).click();

  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Finish" }).click();
  const tab = await popup;
  await expect(tab).toHaveURL(/\/adding\?colour=3$/);
  // Then on to Google Calendar, as before.
  await expect(tab).toHaveURL(/calendar\.google\.com/);
});
