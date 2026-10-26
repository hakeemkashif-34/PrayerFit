// The Jumuah question at the bottom of the Required page, and on Settings.
// The mock API has KMA's Jumuah at 1:30 (1st) and 2:30 (2nd), and
// Stittsville's at 1:15 (1st). Without a set length, each is 45 minutes.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, HOME_PLACE, KMA, MockApi, STITTSVILLE } from "./mock-api";

const QUESTION = "Generally speaking, which Jumuah would you like to attend?";
const KMA_1ST = /^Kanata Muslim Association 1st Jumuah 1:30 PM to 2:15 PM/;
const KMA_2ND = /^Kanata Muslim Association 2nd Jumuah 2:30 PM to 3:15 PM/;

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
  await expect(page.getByText("This week's times, as an example.")).toBeVisible();
  // Each slot, from its start to its end.
  await expect(page.getByRole("radio")).toHaveCount(2);
  await expect(slot(page, KMA_1ST)).toBeChecked();
  await expect(slot(page, KMA_2ND)).not.toBeChecked();
  // Asked about the masjid before it's saved.
  await api.sent("GET", "/api/jumuah/slots");
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

  await page.locator(".slot", { hasText: "2nd Jumuah" }).click();
  await expect(slot(page, KMA_2ND)).toBeChecked();
  await expect(slot(page, KMA_1ST)).not.toBeChecked();
  await expect(page.locator(".slot.selected")).toContainText("2nd Jumuah");
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

  await expect(slot(page, /1st Jumuah 1:30 PM to 2:10 PM/)).toBeChecked();
  // Later slots sit lower on the calendar.
  const [first, second] = await page.locator(".slot").evaluateAll((blocks) => blocks.map((b) => b.getBoundingClientRect().toJSON()));
  expect(second.top).toBeGreaterThan(first.bottom - 1);
});

test("a masjid with no Jumuah times yet skips the question and saves the 1st Jumuah", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.jumuahTimes = {};
  await api.install(page);
  await page.goto("/");
  await atMasjid(page);

  await api.sent("GET", "/api/jumuah/slots");
  await expect(question(page)).toHaveCount(0);
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
  await page.locator(".slot", { hasText: "2nd Jumuah" }).click();

  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox", { name: "Masjid" }).pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();

  await expect(page.getByRole("radio")).toHaveCount(1);
  await expect(slot(page, /^Stittsville Masjid 1st Jumuah 1:15 PM to 2:00 PM/)).toBeChecked();
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
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [KMA, STITTSVILLE] });
  await api.install(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(page.getByRole("radio")).toHaveCount(3);

  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  for (const box of await page.locator(".slot").evaluateAll((blocks) => blocks.map((b) => b.getBoundingClientRect().toJSON()))) {
    expect(box.right).toBeLessThanOrEqual(width);
  }
});

test("on Settings, the pick is in the Required section and changed with the same view", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [KMA] });
  await api.install(page);
  await page.goto("/");
  const row = page.getByRole("region", { name: "Required" }).getByRole("region", { name: "Jumuah pick" });
  await expect(row).toContainText("The earliest Jumuah that fits your calendar");

  await page.getByRole("button", { name: "Edit jumuah pick" }).click();
  await expect(question(page)).toBeVisible();
  // Settings has a short name, so the blocks use it.
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
  await expect(page.getByText("None of your Jumuah masjids have Jumuah times yet.")).toBeVisible();
});
