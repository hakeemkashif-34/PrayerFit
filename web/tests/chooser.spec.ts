// The Jumuah chooser, on setup's page 2 and on Settings. The mock API works
// out each window like the backend: KMA's Jumuah is at 1:30 and 2:30 with a
// 14 minute drive, Stittsville's at 1:15 with a 20 minute drive.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, HOME_PLACE, KMA, MockApi, STITTSVILLE } from "./mock-api";
import type { Settings } from "../src/types";

// Page 1 already answered on an earlier visit, so setup opens on page 2.
function onPage2(jumuah = [KMA, STITTSVILLE]): Settings {
  return {
    ...new MockApi().settings,
    address: HOME_PLACE, place_name: HOME_PLACE, time_zone: "America/Toronto",
    main_masjid_choice: "masjid", main_masjid: KMA, jumuah_saved: true, jumuah_masjids: jumuah,
    weekly: [0, 1, 2, 3, 4, 5, 6].map((weekday) => ({ weekday, fajr: false, dhuhr: false, asr: false, maghrib: false, isha: false })),
  };
}

const slot = (page: Page, name: RegExp) => page.getByRole("radio", { name });
const KMA_1ST = /^Kanata Muslim Association 1st Jumuah at 1:30 PM/;
const KMA_2ND = /^Kanata Muslim Association 2nd Jumuah at 2:30 PM/;
const STITTSVILLE_1ST = /^Stittsville Masjid 1st Jumuah at 1:15 PM/;

test("busy slots are grey, ones that fit are green, and the earliest that fits is picked", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2());
  api.busy = [["13:00", "13:40"]];
  await api.install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Jumuah on Friday, Oct 30" })).toBeVisible();
  // Earliest first, each with its masjid, time, drive, and window.
  await expect(page.getByRole("radio")).toHaveCount(3);
  await expect(slot(page, STITTSVILLE_1ST)).toHaveAccessibleName(
    /20 min drive Leave 12:50 PM, done 2:00 PM \(end time estimated\) Clashes with your calendar/,
  );
  await expect(slot(page, KMA_1ST)).toHaveAccessibleName(/14 min drive Leave 1:11 PM, done 2:15 PM.*Clashes/);
  await expect(slot(page, KMA_2ND)).toHaveAccessibleName(/Leave 2:11 PM, done 3:15 PM.*Fits/);
  await expect(page.locator(".slot.clashes")).toHaveCount(2);
  await expect(page.locator(".slot.fits")).toHaveCount(1);
  await expect(page.locator(".busy-block")).toHaveText("Busy 1:00 PM to 1:40 PM");
  await expect(slot(page, KMA_2ND)).toBeChecked();
});

test("a grey slot can still be picked, and Finish saves it", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2());
  api.busy = [["13:00", "13:40"]];
  await api.install(page);
  await page.goto("/");
  await expect(slot(page, KMA_2ND)).toBeChecked();

  await page.locator(".slot", { hasText: "Stittsville Masjid" }).click();
  await expect(slot(page, STITTSVILLE_1ST)).toBeChecked();
  await expect(slot(page, KMA_2ND)).not.toBeChecked();
  await page.getByRole("button", { name: "Finish" }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: STITTSVILLE.id, order: 1 });
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});

test("the slots can be picked with the keyboard", async ({ page }) => {
  await new MockApi().signedIn(onPage2()).install(page);
  await page.goto("/");
  await expect(slot(page, STITTSVILLE_1ST)).toBeChecked();

  await slot(page, STITTSVILLE_1ST).focus();
  await page.keyboard.press("ArrowDown");
  await expect(slot(page, KMA_1ST)).toBeChecked();
});

test("with no Jumuah times this week, setup skips the chooser", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2());
  api.jumuahTimes = {};
  await api.install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Optional" })).toBeVisible();
  await api.sent("POST", "/api/jumuah/choices");
  await expect(page.getByRole("heading", { name: /^Jumuah on/ })).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Finish" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  expect(api.calls("PUT", "/api/settings/jumuah-pick")).toHaveLength(0);
});

test("the windows follow the Jumuah how early typed, before it's saved", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2([KMA]));
  await api.install(page);
  await page.goto("/");
  await expect(slot(page, KMA_1ST)).toHaveAccessibleName(/14 min drive Leave 1:11 PM/);

  await page.getByLabel("How early do you want to arrive before Jumuah (Friday prayer)?").fill("20");
  // 1:30, 20 minutes early, 14 minute drive: leave 12:56.
  await expect(slot(page, KMA_1ST)).toHaveAccessibleName(/14 min drive Leave 12:56 PM/);
  const last = api.calls("POST", "/api/jumuah/choices").at(-1)!;
  expect(last.body).toEqual({ jumuah_arrive_early_minutes: 20 });
  // Typing pauses are waited for, so not every key press asks again.
  expect(api.calls("POST", "/api/jumuah/choices").length).toBeLessThan(4);
  // Nothing was saved.
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});

test("an unknown drive time starts the window at arrival", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2([KMA]));
  api.jumuahTimes = { [KMA.id]: ["13:30"] };
  // No driving estimate for this masjid, like OpenRouteService finding no route.
  api.orsMinutes = {};
  await api.install(page);
  await page.goto("/");

  await expect(slot(page, KMA_1ST)).toHaveAccessibleName(/Drive time unknown Arrive 1:25 PM, done 2:15 PM/);
});

test("without free/busy access, the chooser says busy times weren't checked", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2([KMA]));
  api.busyChecked = false;
  api.busy = [["13:00", "13:40"]];
  await api.install(page);
  await page.goto("/");

  await expect(page.getByText("Your calendar's busy times couldn't be checked.")).toBeVisible();
  await expect(page.locator(".busy-block")).toHaveCount(0);
  await expect(page.locator(".slot.fits")).toHaveCount(2);
});

test("the day view fits a phone screen with no sideways scrolling", async ({ page }) => {
  const api = new MockApi().signedIn(onPage2());
  api.busy = [["13:00", "13:40"]];
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("radio")).toHaveCount(3);

  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  for (const box of await page.locator(".slot").evaluateAll((cards) => cards.map((c) => c.getBoundingClientRect().toJSON()))) {
    expect(box.right).toBeLessThanOrEqual(width);
  }
});

test("the pick is changed on Settings", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [KMA] });
  await api.install(page);
  await page.goto("/");
  const row = page.getByRole("region", { name: "Jumuah pick" });
  await expect(row).toContainText("The earliest Jumuah that fits your calendar");

  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  // Settings has a short name, so the cards use it.
  await expect(page.getByRole("radio", { name: /^KMA 1st Jumuah/ })).toBeChecked();
  await page.locator(".slot", { hasText: "2nd Jumuah" }).click();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 2 });
  await expect(row).toContainText("2nd Jumuah at Kanata Muslim Association, if it fits your calendar");
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 2 events sent to Google.");

  // Editing again starts from the saved pick.
  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(page.getByRole("radio", { name: /^KMA 2nd Jumuah/ })).toBeChecked();
});

test("Settings says when there are no Jumuah times to pick from", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [KMA] });
  api.jumuahTimes = {};
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(page.getByText("None of your Jumuah masjids have Jumuah times for this Friday yet.")).toBeVisible();
});
