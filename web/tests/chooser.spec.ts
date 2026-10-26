// The Jumuah question at the bottom of the Required page, and on Settings.
// Jumuah is always at the main masjid. It's
// a Friday in a day calendar, each slot a block from when to leave home to
// the end of Jumuah. The mock API has KMA's Jumuah at 1:30 (1st) and 2:30
// (2nd), and Stittsville's at 1:15 (1st). Without a set length, each is 45
// minutes. The drive is 14 minutes to KMA and 20 to Stittsville, and the
// Jumuah "how early" is 5 in setup (10 on the finished Settings).

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, HOME_PLACE, KMA, MockApi, STITTSVILLE } from "./mock-api";

const QUESTION = "Generally speaking, which Jumuah would you like to attend?";
const KMA_1ST = /Kanata Muslim Association 1st Jumuah 1:30 to 2:15 PM/;
const KMA_2ND = /Kanata Muslim Association 2nd Jumuah 2:30 to 3:15 PM/;

const slot = (page: Page, name: RegExp) => page.getByRole("radio", { name });
const question = (page: Page) => page.getByRole("heading", { name: QUESTION });

// Page 1 with the location saved and a masjid picked (not saved yet).
async function atMasjid(page: Page) {
  await page.getByRole("combobox", { name: "Address" }).pressSequentially("200 Kanata", { delay: 30 });
  await page.getByRole("option", { name: HOME_PLACE }).click();
  await expect(page.getByRole("combobox", { name: "Masjid" })).toBeEnabled();
  await page.getByRole("combobox", { name: "Masjid" }).pressSequentially("Kanata", { delay: 30 });
  await page.getByRole("option", { name: /^Kanata Muslim Association/ }).click();
}

test("the question comes last on the Required page, with the 1st Jumuah picked", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);

  const headings = page.getByRole("main").getByRole("heading", { level: 2 });
  await expect(headings.last()).toHaveText(QUESTION);
  await expect(page.getByText("This week's Friday, as an example.")).toBeVisible();
  // Each slot, from its start to its end.
  await expect(page.getByRole("radio")).toHaveCount(2);
  await expect(slot(page, KMA_1ST)).toBeChecked();
  await expect(slot(page, KMA_2ND)).not.toBeChecked();
  // Asked about the masjid before it's saved.
  await api.sent("POST", "/api/jumuah/slots");
  expect(api.calls("PUT", "/api/settings/main-masjid")).toHaveLength(0);
  // Not about one Friday, and nothing from the user's calendar.
  await expect(page.getByText(/Friday, Oct|Busy|Fits|Clashes/)).toHaveCount(0);

  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 1 });
  await expect(page.getByRole("heading", { level: 1, name: "Optional" })).toBeVisible();
});

test("clicking a block picks it, and Next saves it by order", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);

  await page.locator(".friday-slot", { hasText: "2nd Jumuah" }).click();
  await expect(slot(page, KMA_2ND)).toBeChecked();
  await expect(slot(page, KMA_1ST)).not.toBeChecked();
  await expect(page.locator(".friday-slot.selected")).toContainText("2nd Jumuah");
  await page.getByRole("button", { name: "Next" }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 2 });
});

test("the slots can be picked with the keyboard", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await atMasjid(page);
  await expect(slot(page, KMA_1ST)).toBeChecked();

  await slot(page, KMA_1ST).focus();
  await page.keyboard.press("ArrowDown");
  await expect(slot(page, KMA_2ND)).toBeChecked();
});

test("blocks run from start to end, using the masjid's Jumuah length", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.jumuahLength = { [KMA.id]: 40 };
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);

  await expect(slot(page, /1st Jumuah 1:30 to 2:10 PM/)).toBeChecked();
  // Later slots sit lower on the calendar.
  const [first, second] = await page.locator(".friday-slot").evaluateAll((blocks) => blocks.map((b) => b.getBoundingClientRect().toJSON()));
  expect(second.top).toBeGreaterThan(first.bottom - 1);
});

test("a masjid with no Jumuah times yet says so by name and saves the 1st Jumuah", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.jumuahTimes = {};
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);

  await api.sent("POST", "/api/jumuah/slots");
  // Never skipped silently.
  await expect(question(page)).toBeVisible();
  await expect(page.getByText(
    "Jumuah times for Kanata Muslim Association aren't available yet. We'll use the 1st Jumuah, and you can change it in Settings later.",
  )).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 1 });
});

test("praying at home skips the question", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);
  await expect(question(page)).toBeVisible();

  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("button", { name: "I pray at home" }).click();
  await expect(question(page)).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Optional" })).toBeVisible();
  // No Jumuah masjid, so there's nothing to save a pick for.
  expect(api.calls("PUT", "/api/settings/jumuah-pick")).toHaveLength(0);
});

test("a different masjid asks again, about that masjid", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);
  await page.locator(".friday-slot", { hasText: "2nd Jumuah" }).click();

  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox", { name: "Masjid" }).pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();

  await expect(page.getByRole("radio")).toHaveCount(1);
  await expect(slot(page, /Stittsville Masjid 1st Jumuah 1:15 to 2:00 PM/)).toBeChecked();
  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: STITTSVILLE.id, order: 1 });
});

test("the Optional page has no Jumuah question", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await atMasjid(page);
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Optional" })).toBeVisible();
  await expect(question(page)).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
});

test("the calendar view fits a phone screen with no sideways scrolling", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(page.getByRole("radio")).toHaveCount(2);

  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  for (const box of await page.locator(".friday-slot").evaluateAll((blocks) => blocks.map((b) => b.getBoundingClientRect().toJSON()))) {
    expect(box.right).toBeLessThanOrEqual(width);
  }
});

test("on Settings, the pick is in the Required section and changed with the same view", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");
  const row = page.getByRole("region", { name: "Required" }).getByRole("region", { name: "Jumuah pick" });
  await expect(row).toContainText("The earliest Jumuah that fits your calendar");

  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(question(page)).toBeVisible();
  // Settings has a short name, so the blocks use it.
  await expect(page.getByRole("radio", { name: /KMA 1st Jumuah/ })).toBeChecked();
  await page.locator(".friday-slot", { hasText: "2nd Jumuah" }).click();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 2 });
  // Just the pick, nothing more.
  await expect(row.locator(".row-value")).toHaveText("2nd Jumuah");
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 2 events sent to Google.");

  // Editing again starts from the saved pick.
  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(page.getByRole("radio", { name: /KMA 2nd Jumuah/ })).toBeChecked();
});

test("Settings says when there are no Jumuah times to pick from", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.jumuahTimes = {};
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  // On Settings it doesn't say "change it in Settings later".
  await expect(page.locator(".chooser .notice")).toHaveText("Jumuah times for KMA aren't available yet.");
});

test("it looks like a Friday in a calendar: 11 AM to 4 PM, the rest greyed out", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await atMasjid(page);
  await expect(slot(page, KMA_1ST)).toBeChecked();

  await expect(page.locator(".friday-head")).toHaveText("Friday");
  await expect(page.locator(".friday-hour")).toHaveText(["11 AM", "12 PM", "1 PM", "2 PM", "3 PM", "4 PM"]);
  // Everything that isn't a block is greyed out (a striped grey background).
  expect(await page.locator(".friday-day").evaluate((el) => getComputedStyle(el).backgroundImage)).toContain("gradient");
});

test("each block starts at the leave time and ends at the end of Jumuah", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await atMasjid(page);
  // 1:30 Jumuah, 5 minutes early, a 14 minute drive: leave at 1:11. 45 minutes long: ends 2:15.
  const first = page.locator(".friday-slot", { hasText: "1st Jumuah" });
  await expect(first.locator(".slot-leave")).toHaveText("Leave 1:11 PM");

  const [block, hour1, hour2] = await Promise.all([
    first.boundingBox(),
    page.locator(".friday-hour", { hasText: /^1 PM$/ }).boundingBox(),
    page.locator(".friday-hour", { hasText: /^2 PM$/ }).boundingBox(),
  ]);
  const perMinute = (hour2!.y - hour1!.y) / 60;
  // 11 minutes after 1 PM, and 64 minutes long, give or take a pixel.
  expect(Math.abs(block!.y - (hour1!.y + 11 * perMinute))).toBeLessThan(2);
  expect(Math.abs(block!.height - 64 * perMinute)).toBeLessThan(2);
});

test("the picked block is solid green with a tick, and only that one", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await atMasjid(page);
  const picked = page.locator(".friday-slot.selected");
  await expect(picked).toHaveCount(1);
  await expect(picked).toContainText("1st Jumuah");
  await expect(picked).toContainText("✓ Selected");
  await expect(page.locator(".friday-slot:not(.selected)")).not.toContainText("Selected");
  const [background, text] = await picked.evaluate((el) => [getComputedStyle(el).backgroundColor, getComputedStyle(el).color]);
  expect(background).toBe("rgb(23, 102, 63)");
  expect(text).toBe("rgb(255, 255, 255)");
});
