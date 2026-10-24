import { expect, test } from "@playwright/test";
import { FOUND, MockApi } from "./mock-api";

test("the full setup flow, from address to a filled calendar", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  // 1. Address: typing alone never searches. Only the button does.
  await expect(page.getByText("Step 1 of 5")).toBeVisible();
  await page.getByRole("textbox", { name: "Address" }).fill("200 Kanata Ave, Ottawa");
  expect(api.calls("POST", "/api/setup/address/search")).toHaveLength(0);
  await expect(page.getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();
  await page.getByRole("button", { name: "Find address" }).click();
  await expect(page.getByTestId("found-place")).toHaveText(FOUND.place_name);
  await expect(page.getByText("Time zone: America/Toronto")).toBeVisible();
  await page.getByRole("button", { name: "Yes, that's it" }).click();
  expect(api.calls("PUT", "/api/settings/address")[0].body).toEqual({ address: "200 Kanata Ave, Ottawa" });

  // 2. Methods: ISNA and standard are picked already.
  await expect(page.getByText("Step 2 of 5")).toBeVisible();
  await expect(page.getByRole("radio", { name: /ISNA/ })).toBeChecked();
  await expect(page.getByRole("radio", { name: /Standard/ })).toBeChecked();
  await expect(page.getByText("Most masjids in North America use this.")).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  expect(api.calls("PUT", "/api/settings/methods")[0].body).toEqual({ method: "isna", asr_method: "standard" });

  // 3. Main masjid: closest first, with distances and no ratings.
  await expect(page.getByText("Step 3 of 5")).toBeVisible();
  const names = page.locator("label.choice strong");
  await expect(names).toHaveText([
    "Kanata Muslim Association", "Stittsville Masjid", "No name on OpenStreetMap", "My masjid isn't listed", "I pray at home",
  ]);
  await expect(page.getByText("1.1 km away")).toBeVisible();
  await expect(page.getByText("Iqamah times not added yet").first()).toBeVisible();
  await page.getByRole("radio", { name: /Kanata Muslim Association/ }).check();
  await expect(page.getByText('Events will say "Dhuhr at Kanata Muslim Association".')).toBeVisible();
  await page.getByLabel("Short name for your calendar (optional)").fill("KMA");
  await expect(page.getByText('Events will say "Dhuhr at KMA".')).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();
  expect(api.calls("PUT", "/api/settings/main-masjid")[0].body).toEqual({
    choice: "masjid", masjid_id: "11111111-1111-1111-1111-111111111111", short_name: "KMA",
  });

  // 4. Weekly grid: Monday to Sunday, 5 prayers each.
  await expect(page.getByText("Step 4 of 5")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Which prayers do you usually pray at KMA?" })).toBeVisible();
  await expect(page.getByRole("checkbox")).toHaveCount(35);
  await page.getByLabel("Dhuhr on Monday at the masjid").check();
  await page.getByLabel("Isha on Friday at the masjid").check();
  await page.getByLabel("Fajr on Sunday at the masjid").check();
  await page.getByRole("button", { name: "Save" }).click();
  const days = (api.calls("PUT", "/api/settings/weekly")[0].body as { days: Record<string, unknown>[] }).days;
  expect(days).toHaveLength(7);
  expect(days[0]).toEqual({ weekday: 0, fajr: false, dhuhr: true, asr: false, maghrib: false, isha: false });
  expect(days[4].isha).toBe(true);
  expect(days[6].fajr).toBe(true);

  // 5. Jumuah: more than one.
  await expect(page.getByText("Step 5 of 5")).toBeVisible();
  await page.getByRole("checkbox", { name: /Kanata Muslim Association/ }).check();
  await page.getByRole("checkbox", { name: /Stittsville Masjid/ }).check();
  await page.getByRole("button", { name: "Save" }).click();
  expect(api.calls("PUT", "/api/settings/jumuah")[0].body).toEqual({
    masjid_ids: ["11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"],
  });

  // Finish: the calendar gets 14 days of prayers.
  await page.getByRole("button", { name: "Fill my calendar" }).click();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 70 events sent to Google.");
  await expect(page.getByRole("heading", { name: "Your prayers" })).toBeVisible();
  await expect(page.getByText("Kanata Muslim Association (KMA)")).toBeVisible();
});

test("I pray at home skips the weekly grid", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await page.getByRole("textbox", { name: "Address" }).fill("200 Kanata Ave, Ottawa");
  await page.getByRole("button", { name: "Find address" }).click();
  await page.getByRole("button", { name: "Yes, that's it" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await page.getByRole("radio", { name: "I pray at home" }).check();
  await expect(page.getByLabel("Short name for your calendar (optional)")).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();

  // Straight to Jumuah, now step 4 of 4.
  await expect(page.getByText("Step 4 of 4")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Where can you go for Jumuah?" })).toBeVisible();
  await page.getByRole("button", { name: "Save with no Jumuah masjid" }).click();
  await page.getByRole("button", { name: "Fill my calendar" }).click();
  await expect(page.getByText("I pray at home")).toBeVisible();
  expect(api.calls("PUT", "/api/settings/weekly")).toHaveLength(0);
});

test("My masjid isn't listed saves a typed-in masjid", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.settings = { ...api.settings, address: "x", place_name: "x", time_zone: "America/Toronto", method: "isna", asr_method: "standard" };
  await api.install(page);
  await page.goto("/");

  await page.getByRole("radio", { name: "My masjid isn't listed" }).check();
  await page.getByLabel("Masjid name").fill("Barrhaven Musalla");
  await page.getByLabel("Masjid address").fill("3500 Fallowfield Rd");
  await page.getByRole("button", { name: "Save" }).click();

  expect(api.calls("PUT", "/api/settings/main-masjid")[0].body).toEqual({
    choice: "custom", name: "Barrhaven Musalla", address: "3500 Fallowfield Rd",
  });
  await expect(page.getByRole("heading", { name: "Which prayers do you usually pray at Barrhaven Musalla?" })).toBeVisible();
});

test("a busy address search shows its message", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/address/search"] = {
    status: 503,
    detail: { message: "OpenStreetMap's address search is busy. Try again in a minute." },
  };
  await api.install(page);
  await page.goto("/");

  await page.getByRole("textbox", { name: "Address" }).fill("200 Kanata Ave, Ottawa");
  await page.getByRole("button", { name: "Find address" }).click();

  await expect(page.getByRole("alert")).toHaveText("OpenStreetMap's address search is busy. Try again in a minute.");
});
