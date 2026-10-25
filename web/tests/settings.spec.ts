import { expect, test } from "@playwright/test";
import { finishedSettings, GOOGLE_CALENDAR, KMA, MockApi } from "./mock-api";

test("the settings page shows every saved setting with an Edit button", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByText("Signed in as hakeem@example.com")).toBeVisible();
  for (const name of ["location", "prayer time method", "main masjid", "prayers at the masjid", "jumuah masjids", "extras"]) {
    await expect(page.getByRole("button", { name: `Edit ${name}` })).toBeVisible();
  }
  await expect(page.getByText("ISNA, Standard Asr")).toBeVisible();
  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  await expect(page.getByText("Saturday: all at home")).toBeVisible();
  // Where each masjid's times come from.
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Times from MAWAQIT, updated Oct 25, 2026");
  const extras = page.getByRole("region", { name: "Extras" });
  await expect(extras).toContainText("Arrive 5 min before iqamah");
  await expect(extras).toContainText("Prayer colour: Peacock");
  await expect(extras).toContainText("Drive colour: Calendar colour");
  // The old "Your prayers" title is gone: this page is Settings now.
  await expect(page.getByText("Your prayers")).toHaveCount(0);
  // The page shows OpenStreetMap data and OpenRouteService drive times, so both credits are in its footer.
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();
  await expect(footer.getByRole("link", { name: "Drive times © openrouteservice.org by HeiGIT" })).toBeVisible();
});

test("returning users land on Settings with an Open Google Calendar button, and no redirect", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  const open = page.getByRole("link", { name: "Open Google Calendar" });
  await expect(open).toHaveAttribute("href", GOOGLE_CALENDAR);
  // Give a redirect time to happen, if there were one.
  await page.waitForTimeout(500);
  expect(api.googleVisits).toEqual([]);
  expect(new URL(page.url()).host).toBe("localhost:4173");

  await open.click();
  await expect(page).toHaveURL(GOOGLE_CALENDAR);
  expect(api.googleVisits).toEqual([GOOGLE_CALENDAR]);
});

test("editing a setting saves it and says what changed in the calendar", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayer time method" }).click();
  await page.getByRole("radio", { name: /Hanafi/ }).check();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/methods", 1))[0].body).toEqual({ method: "isna", asr_method: "hanafi" });
  await expect(page.getByText("ISNA, Hanafi Asr")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 3 events sent to Google.");
});

test("a save that can't reach Google offers Sign in again", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.route("**/api/settings/methods", (route) =>
    route.fulfill({
      json: {
        settings: finishedSettings(),
        calendar: { status: "sign_in_needed", sent: 0, waiting: 69, message: "Saved. Sign in again so your calendar can update." },
      },
    }),
  );
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayer time method" }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toContainText("Saved. Sign in again so your calendar can update.");
  await expect(page.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
});

test("editing the location picks a new place from the suggestions", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit location" }).click();
  await page.getByRole("combobox").pressSequentially("Robson", { delay: 30 });
  await page.getByRole("option", { name: "1 Robson Street, Vancouver, British Columbia, Canada" }).click();

  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "Robson", index: 0 });
  await expect(page.getByText("1 Robson Street, Vancouver, British Columbia, Canada")).toBeVisible();
});

test("cancel leaves the setting as it was", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();
  await page.getByLabel("Asr on Monday at the masjid").check();
  await page.getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  expect(api.calls("PUT", "/api/settings/weekly")).toHaveLength(0);
});

test("picking a masjid after praying at home asks for the weekly grid", async ({ page }) => {
  const settings = { ...finishedSettings(), main_masjid_choice: "home" as const, main_masjid: null, weekly: [] };
  const api = new MockApi().signedIn(settings);
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("heading", { name: "Which prayers do you usually pray at Stittsville Masjid?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
});

test("picking a different masjid clears the old short name", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("(KMA)");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await expect(page.getByLabel(/Short name/)).toHaveCount(0);
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({
    choice: "masjid", masjid_id: "22222222-2222-2222-2222-222222222222",
  });
  await expect(page.getByRole("region", { name: "Main masjid" })).not.toContainText("(KMA)");
  await page.getByRole("button", { name: "Edit extras" }).click();
  await expect(page.getByLabel("Short name for Stittsville Masjid (optional)")).toHaveValue("");
});

test("editing the extras: how early, short name, and colours", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit extras" }).click();
  const early = page.getByLabel("How early do you want to arrive before iqamah?");
  // Answered before, so it shows what was saved, not the defaults.
  await expect(early).toHaveValue("5");
  await early.fill("30");
  const shortName = page.getByLabel("Short name for Kanata Muslim Association (optional)");
  await expect(shortName).toHaveValue("KMA");
  await shortName.fill("Kanata");
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Peacock");
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  await page.getByRole("option", { name: "Calendar colour" }).click();
  await page.getByRole("button", { name: /^Drive colour/ }).click();
  await page.getByRole("option", { name: "Banana" }).click();
  // No Skip on the settings page, just Save and Cancel.
  await expect(page.getByRole("button", { name: "Skip" })).toHaveCount(0);
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({
    arrive_early_minutes: 30, short_name: "Kanata", prayer_color_id: null, drive_color_id: "5",
  });
  const extras = page.getByRole("region", { name: "Extras" });
  await expect(extras).toContainText("Arrive 30 min before iqamah");
  await expect(extras).toContainText("Prayer colour: Calendar colour");
  await expect(extras).toContainText("Drive colour: Banana");
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("(Kanata)");
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 20 events sent to Google.");
});

test("cancel leaves the extras as they were", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit extras" }).click();
  await page.getByLabel("How early do you want to arrive before iqamah?").fill("0");
  await page.getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByRole("region", { name: "Extras" })).toContainText("Arrive 5 min before iqamah");
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});

test("a new main masjid takes the old one's place as the Jumuah masjid", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [KMA] });
  await api.install(page);
  await page.goto("/");
  const jumuah = page.getByRole("region", { name: "Jumuah masjids" });
  await expect(jumuah.getByRole("listitem")).toHaveText([/^Kanata Muslim Association/]);

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(jumuah.getByRole("listitem")).toHaveText([/^Stittsville Masjid/]);
});

test("a Jumuah list the user chose stays when the main masjid changes", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings()); // Jumuah: KMA and Stittsville
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Stittsville Masjid");
  await expect(page.getByRole("region", { name: "Jumuah masjids" }).getByRole("listitem")).toHaveText([
    /^Kanata Muslim Association/, /^Stittsville Masjid/,
  ]);
});

test("I pray at home on the settings page moves every prayer home", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("button", { name: "I pray at home" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "home" });
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("I pray at home");
  await expect(page.getByRole("region", { name: "Prayers at the masjid" })).toHaveCount(0);
});

test("Jumuah masjids are added with the masjid search and can be removed", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit jumuah masjids" }).click();
  await page.getByRole("button", { name: "Remove Stittsville Masjid" }).click();
  await page.getByRole("combobox").pressSequentially("Toronto", { delay: 30 });
  await page.getByRole("option", { name: /^Kanata Masjid Toronto/ }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah", 1))[0].body).toEqual({
    masjid_ids: ["11111111-1111-1111-1111-111111111111", "33333333-3333-3333-3333-333333333333"],
  });
  await expect(page.getByRole("region", { name: "Jumuah masjids" })).toContainText("Kanata Masjid Toronto");
});

test("Jumuah masjids keep the order they were added in, each with where its times come from", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_masjids: [] });
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Jumuah masjids" })).toContainText("None picked");

  await page.getByRole("button", { name: "Edit jumuah masjids" }).click();
  for (const [typed, name] of [["Stittsville", "Stittsville Masjid"], ["Kanata Muslim", "Kanata Muslim Association"]]) {
    await page.getByRole("combobox").fill("");
    await page.getByRole("combobox").pressSequentially(typed, { delay: 30 });
    await page.getByRole("option", { name: new RegExp(`^${name}`) }).click();
    await expect(page.locator("ul.picked-list")).toContainText(name);
  }
  await page.getByRole("button", { name: "Save", exact: true }).click();

  expect((await api.sent("PUT", "/api/settings/jumuah", 1))[0].body).toEqual({
    masjid_ids: ["22222222-2222-2222-2222-222222222222", "11111111-1111-1111-1111-111111111111"],
  });
  await expect(page.getByRole("region", { name: "Jumuah masjids" }).getByRole("listitem")).toHaveText([
    "Stittsville Masjid · Not linked to MAWAQIT, so calculated times are used",
    "Kanata Muslim Association · Times from MAWAQIT, updated Oct 25, 2026",
  ]);
});

test("sign out calls the API and goes back to the sign-in screen", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
  expect(api.calls("POST", "/auth/logout")).toHaveLength(1);
  // Reloading stays signed out.
  await page.reload();
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
});

test("existing users keep their own extras, not the new defaults", async ({ page }) => {
  // Saved before the defaults changed: 0 minutes and the calendar's colour.
  const api = new MockApi().signedIn({ ...finishedSettings(), arrive_early_minutes: 0, prayer_color_id: null, drive_color_id: null });
  await api.install(page);
  await page.goto("/");
  const extras = page.getByRole("region", { name: "Extras" });
  await expect(extras).toContainText("Arrive at iqamah time");
  await expect(extras).toContainText("Prayer colour: Calendar colour");

  await page.getByRole("button", { name: "Edit extras" }).click();
  await expect(page.getByLabel("How early do you want to arrive before iqamah?")).toHaveValue("0");
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Calendar colour");
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toContainText("Calendar colour");
});

test("a bad how early number on the Settings page shows the error and saves nothing", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit extras" }).click();
  await page.getByLabel("How early do you want to arrive before iqamah?").fill("45");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("alert")).toHaveText("Enter a whole number of minutes from 0 to 30.");
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});
