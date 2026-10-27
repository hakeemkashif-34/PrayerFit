import { expect, test } from "@playwright/test";
import { finishedSettings, GOOGLE_CALENDAR, KMA, MockApi, openEditor } from "./mock-api";

test("Settings has 2 cards, Required and Optional, each item with its own Edit", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByText("Signed in as hakeem@example.com")).toBeVisible();
  const required = page.getByRole("region", { name: "Required" });
  const optional = page.getByRole("region", { name: "Optional" });
  for (const name of ["Location", "Main masjid", "Prayers at the masjid", "Preferred Jumuah"]) {
    await expect(required.getByRole("region", { name })).toBeVisible();
  }
  const optionalItems = [
    "Short name", "Arrive before iqamah", "Arrive before Jumuah",
    "Prayer colour", "Drive colour", "Notify before leaving", "Notify before home prayers",
  ];
  for (const name of optionalItems) {
    await expect(optional.getByRole("region", { name })).toBeVisible();
  }
  for (const name of ["Location", "Main masjid", "Prayers at the masjid", "Preferred Jumuah", ...optionalItems]) {
    await expect(page.getByRole("button", { name: `Edit ${name.toLowerCase()}` })).toBeVisible();
  }
  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  await expect(page.getByText("Saturday: all at home")).toBeVisible();
  // Where each masjid's times come from.
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Times from MAWAQIT, updated Oct 25, 2026");
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("KMA");
  // A short label, and just the answer as the value.
  const early = page.getByRole("region", { name: "Arrive before iqamah" });
  await expect(early.locator("h3")).toHaveText("Arrive before iqamah");
  await expect(early.locator(".row-value")).toHaveText("5 minutes");
  const jumuahEarly = page.getByRole("region", { name: "Arrive before Jumuah" });
  await expect(jumuahEarly.locator("h3")).toHaveText("Arrive before Jumuah");
  await expect(jumuahEarly.locator(".row-value")).toHaveText("10 minutes");
  await expect(page.getByText(/Arrive \d+ min/)).toHaveCount(0);
  // Every label, in order: as short as possible, and never a long setup question.
  await expect(page.locator(".setting-row h3")).toHaveText([
    "Location", "Main masjid", "Prayers at the masjid", "Preferred Jumuah",
    "Short name", "Arrive before iqamah", "Arrive before Jumuah", "Prayer colour", "Drive colour",
    "Notify before leaving", "Notify before home prayers",
  ]);
  await expect(page.locator(".setting-row h3", { hasText: "?" })).toHaveCount(0);
  // Jumuah is always at the main masjid, so there's no Jumuah masjids setting.
  await expect(page.getByRole("region", { name: "Jumuah masjids" })).toHaveCount(0);
  // How often the calendar catches up.
  await expect(page.getByText("Updates and changes are reflected on your calendar every 5 minutes.")).toBeVisible();
  // "every 5 minutes" has the same soft yellow as "praying on time" on the landing page, in bold.
  const highlight = page.locator("mark.highlight");
  await expect(highlight).toHaveCount(1);
  await expect(highlight).toHaveText("every 5 minutes");
  await expect(highlight).toHaveCSS("background-color", "rgb(251, 224, 138)");
  await expect(highlight).toHaveCSS("font-weight", "700");
  await expect(page.getByRole("region", { name: "Prayer colour" })).toContainText("Peacock");
  await expect(page.getByRole("region", { name: "Drive colour" })).toContainText("Calendar colour");
  // Drive times always come from OpenRouteService, so there's nothing to set for them.
  await expect(page.getByText(/commute/i)).toHaveCount(0);
  // The prayer time method is gone: times always use ISNA with standard Asr.
  await expect(page.getByText(/method/i)).toHaveCount(0);
  await expect(page.getByText("Your prayers")).toHaveCount(0);
  // The page shows OpenStreetMap data and OpenRouteService drive times, so both credits are in its footer.
  const footer = page.getByRole("contentinfo");
  await expect(footer.getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();
  await expect(footer.getByRole("link", { name: "Drive times © openrouteservice.org by HeiGIT" })).toBeVisible();
  // Nothing wider than a phone's screen.
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
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

  await openEditor(page, "Edit prayers at the masjid");
  await page.getByLabel("Asr on Monday at the masjid").check();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/weekly", 1))[0].body).toMatchObject({ days: expect.any(Array) });
  await expect(page.getByText("Monday: Dhuhr, Asr, Isha")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 2 events sent to Google.");
});

test("a save that can't reach Google offers Sign in again", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.route("**/api/settings/weekly", (route) =>
    route.fulfill({
      json: {
        settings: finishedSettings(),
        calendar: { status: "sign_in_needed", sent: 0, waiting: 69, message: "Saved. Sign in again so your calendar can update." },
      },
    }),
  );
  await page.goto("/");

  await openEditor(page, "Edit prayers at the masjid");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toContainText("Saved. Sign in again so your calendar can update.");
  await expect(page.getByRole("status").getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
});

test("editing the location picks a new place from the suggestions", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit location");
  await page.getByRole("combobox").pressSequentially("Robson", { delay: 30 });
  await page.getByRole("option", { name: "1 Robson Street, Vancouver, British Columbia, Canada" }).click();

  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "Robson", index: 0 });
  await expect(page.getByText("1 Robson Street, Vancouver, British Columbia, Canada")).toBeVisible();
});

test("cancel leaves the setting as it was", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit prayers at the masjid");
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

  await openEditor(page, "Edit main masjid");
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
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("KMA");

  await openEditor(page, "Edit main masjid");
  await expect(page.getByRole("textbox", { name: /Short name/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({
    choice: "masjid", masjid_id: "22222222-2222-2222-2222-222222222222",
  });
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("None");
  await openEditor(page, "Edit short name");
  await expect(page.getByLabel("Short name for Stittsville Masjid")).toHaveValue("");
});

// What finishedSettings() has saved for the optional answers.
const SAVED_OPTIONAL = {
  arrive_early_minutes: 5, jumuah_arrive_early_minutes: 10, short_name: "KMA", prayer_color_id: "7", drive_color_id: null,
  // Every editor sends the notifications too, so saving one setting never turns them off.
  leave_reminder_minutes: 5, home_reminder_minutes: 5,
};

test("how early for prayers is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit arrive before iqamah");
  const early = page.getByRole("spinbutton", { name: "Arrive before iqamah" });
  await expect(early).toHaveValue("5");
  await early.fill("45");
  await page.getByRole("button", { name: "Save" }).click();

  // Every other answer is sent as it was saved.
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, arrive_early_minutes: 45 });
  await expect(page.getByRole("region", { name: "Arrive before iqamah" }).locator(".row-value")).toHaveText("45 minutes");
  await expect(page.getByRole("region", { name: "Arrive before Jumuah" }).locator(".row-value")).toHaveText("10 minutes");
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 20 events sent to Google.");
});

test("how early for Jumuah is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit arrive before jumuah");
  await page.getByRole("spinbutton", { name: "Arrive before Jumuah" }).fill("0");
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, jumuah_arrive_early_minutes: 0 });
  await expect(page.getByRole("region", { name: "Arrive before Jumuah" }).locator(".row-value")).toHaveText("0 minutes");
});

test("the short name is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit short name");
  const shortName = page.getByLabel("Short name for Kanata Muslim Association");
  await expect(shortName).toHaveValue("KMA");
  await shortName.fill("Kanata");
  await expect(page.getByText('Events will say "Dhuhr at Kanata".')).toBeVisible();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, short_name: "Kanata" });
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("Kanata");
});

test("each colour is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit prayer colour");
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Peacock");
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  await page.getByRole("option", { name: "Calendar colour" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, prayer_color_id: null });
  await expect(page.getByRole("region", { name: "Prayer colour" })).toContainText("Calendar colour");

  await openEditor(page, "Edit drive colour");
  await page.getByRole("button", { name: /^Drive colour/ }).click();
  await page.getByRole("option", { name: "Banana" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 2))[1].body).toEqual({
    ...SAVED_OPTIONAL, prayer_color_id: null, drive_color_id: "5",
  });
  await expect(page.getByRole("region", { name: "Drive colour" })).toContainText("Banana");
});

test("cancel leaves an optional item as it was", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit arrive before iqamah");
  await page.getByRole("spinbutton", { name: "Arrive before iqamah" }).fill("0");
  await page.getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByRole("region", { name: "Arrive before iqamah" }).locator(".row-value")).toHaveText("5 minutes");
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});

test("only one item is edited at a time", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await openEditor(page, "Edit short name");
  await expect(page.getByRole("button", { name: "Edit location" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Edit prayer colour" })).toBeDisabled();
});

test("a new main masjid moves Jumuah there too, starting at its 1st Jumuah", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_pick: { masjid_id: KMA.id, order: 2 } });
  await api.install(page);
  await page.goto("/");
  const pick = page.getByRole("region", { name: "Preferred Jumuah" });
  await expect(pick.locator(".row-value")).toHaveText("2nd Jumuah");

  await openEditor(page, "Edit main masjid");
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Stittsville Masjid");
  await expect(pick.locator(".row-value")).toHaveText("1st Jumuah");
});

test("I pray at home on the settings page moves every prayer home", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await openEditor(page, "Edit main masjid");
  await page.getByRole("button", { name: "I pray at home" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "home" });
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("I pray at home");
  await expect(page.getByRole("region", { name: "Prayers at the masjid" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Short name" })).toHaveCount(0);
  // Praying at home means no Jumuah.
  await expect(page.getByRole("region", { name: "Preferred Jumuah" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Arrive before Jumuah" })).toHaveCount(0);
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

test("existing users keep their own answers, not the new defaults", async ({ page }) => {
  // Saved before the defaults changed: 0 minutes and the calendar's colour.
  const api = new MockApi().signedIn({ ...finishedSettings(), arrive_early_minutes: 0, prayer_color_id: null, drive_color_id: null });
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Arrive before iqamah" }).locator(".row-value")).toHaveText("0 minutes");
  await expect(page.getByRole("region", { name: "Prayer colour" })).toContainText("Calendar colour");

  await openEditor(page, "Edit arrive before iqamah");
  await expect(page.getByRole("spinbutton", { name: "Arrive before iqamah" })).toHaveValue("0");
  await page.getByRole("button", { name: "Cancel" }).click();
  await openEditor(page, "Edit drive colour");
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toContainText("Calendar colour");
});

test("a bad how early number on the Settings page shows the error and saves nothing", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  for (const [button, label] of [
    ["Edit arrive before iqamah", "Arrive before iqamah"],
    ["Edit arrive before jumuah", "Arrive before Jumuah"],
  ]) {
    await openEditor(page, button);
    await page.getByRole("spinbutton", { name: label }).fill("61");
    await page.getByRole("button", { name: "Save" }).click();
    await expect(page.getByRole("alert")).toHaveText("Enter a whole number of minutes from 0 to 60.");
    await page.getByRole("button", { name: "Cancel" }).click();
  }
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});

test("users without free/busy access get a banner to sign in again", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings(), { busy_access: false });
  await api.install(page);
  await page.goto("/");

  const banner = page.getByRole("region", { name: "Sign in again so your prayers can fit around your calendar." });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText("We only see when you're busy, never what your events are.");
  await expect(banner.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
  // The banner sits above the settings.
  const [bannerBox, card] = await Promise.all([banner.boundingBox(), page.locator(".settings-card.required").boundingBox()]);
  expect(bannerBox!.y).toBeLessThan(card!.y);
});

test("Not now hides the banner, and it stays hidden in this browser", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings(), { busy_access: false });
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Not now" }).click();
  await expect(page.getByText("We only see when you're busy")).toHaveCount(0);
  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByText("We only see when you're busy")).toHaveCount(0);
});

test("users with free/busy access see no banner", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByText("We only see when you're busy")).toHaveCount(0);
});

test("Required is on the left and Optional on the right on a computer, and stacked on a phone", async ({ page }, info) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const [required, optional] = await Promise.all([
    page.getByRole("region", { name: "Required" }).boundingBox(),
    page.getByRole("region", { name: "Optional" }).boundingBox(),
  ]);
  if (info.project.name === "phone") {
    expect(optional!.y).toBeGreaterThan(required!.y + required!.height - 1);
  } else {
    expect(optional!.x).toBeGreaterThan(required!.x + required!.width - 1);
    expect(Math.abs(optional!.y - required!.y)).toBeLessThan(2);
  }
  // Both cards look the same: white, with the same shadow.
  const look = (name: string) =>
    page.getByRole("region", { name }).evaluate((el) => {
      const s = getComputedStyle(el);
      return `${s.backgroundColor} ${s.boxShadow}`;
    });
  expect(await look("Required")).toBe(await look("Optional"));
});

test("labels are small and muted, values larger and darker, and nothing is in all caps", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const row = page.getByRole("region", { name: "Location" });
  const [label, value] = await Promise.all(
    [row.locator("h3"), row.locator(".row-value p").first()].map((l) =>
      l.evaluate((el) => {
        const s = getComputedStyle(el);
        return { size: parseFloat(s.fontSize), colour: s.color, transform: s.textTransform };
      }),
    ),
  );
  expect(label.size).toBeLessThan(value.size);
  expect(label.colour).not.toBe(value.colour);
  expect(label.transform).toBe("none");
  await expect(row.locator("h3")).toHaveText("Location");
});

test("the chosen colours show as swatches", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  // Peacock is #039be5. Drive colour is the calendar's own, an empty ring.
  const swatch = page.getByRole("region", { name: "Prayer colour" }).locator(".swatch");
  await expect(swatch).toHaveCSS("background-color", "rgb(3, 155, 229)");
  await expect(page.getByRole("region", { name: "Drive colour" }).locator(".swatch.none")).toBeVisible();
});

test("buttons show hover and keyboard focus", async ({ page }, info) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const edit = page.getByRole("button", { name: "Edit location" });
  const before = await edit.evaluate((el) => getComputedStyle(el).backgroundColor);
  if (info.project.name !== "phone") {
    await edit.hover();
    await expect.poll(() => edit.evaluate((el) => getComputedStyle(el).backgroundColor)).not.toBe(before);
  }
  await edit.focus();
  await page.keyboard.press("Shift+Tab");
  await page.keyboard.press("Tab");
  await expect(edit).toBeFocused();
  await expect(edit).toHaveCSS("outline-style", "solid");
});

test("an item opens and closes smoothly, and not at all with motion turned off", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const row = page.getByRole("region", { name: "Location", exact: true });
  const easing = () => row.evaluate((el) => el.getAnimations().length);
  // Nothing moves on page load.
  expect(await easing()).toBe(0);
  // A plain click, not openEditor: this test needs to see the row while it's still easing.
  await page.getByRole("button", { name: "Edit location" }).click();
  expect(await easing()).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  await row.getByRole("button", { name: "Cancel" }).click();
  expect(await easing()).toBeGreaterThan(0);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForTimeout(400);
  await openEditor(page, "Edit location");
  expect(await easing()).toBe(0);
});


test("a notice at the top says when a masjid's times couldn't be confirmed", async ({ page }) => {
  // From 24 hours to 7 days the last MAWAQIT times are still used, and the notice says when that stops.
  const notice =
    "KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is still using the last times read " +
    "from MAWAQIT, and switches to calculated times on Oct 31, 2026 if they still can't be read.";
  await new MockApi().signedIn({ ...finishedSettings(), masjid_notices: [notice] }).install(page);
  await page.goto("/");
  const shown = page.getByRole("status").filter({ hasText: notice });
  await expect(shown).toBeVisible();
  // Above both cards.
  const [box, card] = await Promise.all([shown.boundingBox(), page.locator(".settings-card.required").boundingBox()]);
  expect(box!.y).toBeLessThan(card!.y);
});

test("no notice when every masjid's times are fresh", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  await expect(page.getByText(/couldn't be confirmed/)).toHaveCount(0);
});

test("where masjid times come from is on Settings, since events don't say it", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Times from MAWAQIT, updated Oct 25, 2026");
});

test("Location shows the time zone, and no line about the calculation method", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const location = page.getByRole("region", { name: "Location" });
  await expect(location).toContainText("America/Toronto");
  await expect(page.getByText(/ISNA/)).toHaveCount(0);
});

test("the Required and Optional cards and the calendar message share one background", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  await openEditor(page, "Edit prayers at the masjid");
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText(/^Calendar updated/);
  const background = (selector: string) =>
    page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor);
  // White, which stands out on the light green page.
  expect(await background(".settings-card.required")).toBe("rgb(255, 255, 255)");
  expect(await background(".settings-card.optional")).toBe("rgb(255, 255, 255)");
  expect(await page.getByRole("status").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");
});

// Is the answer (or box) on the same line as its question? Same line means their boxes overlap top to bottom.
async function sideBySide(page: import("@playwright/test").Page, question: string, answer: string) {
  const [q, a] = await Promise.all([page.locator(question).boundingBox(), page.locator(answer).boundingBox()]);
  return a!.x >= q!.x + q!.width - 1 && a!.y < q!.y + q!.height && q!.y < a!.y + a!.height;
}

test("each label and its answer share a line when they fit, and wrap only when they don't", async ({ page }, info) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");
  const row = (name: string) => `section.setting-row[aria-label="${name}"]`;
  await expect(page.locator(row("Short name"))).toBeVisible();

  const beside = (name: string) => sideBySide(page, `${row(name)} h3`, `${row(name)} .row-value`);
  // Short labels and short answers fit side by side on every screen.
  expect(await beside("Short name")).toBe(true);
  // On desktop, every Optional row fits on one line.
  if (info.project.name === "desktop") {
    for (const name of ["Arrive before iqamah", "Arrive before Jumuah", "Prayer colour", "Drive colour", "Notify before leaving", "Notify before home prayers"]) {
      expect(await beside(name), name).toBe(true);
    }
  }
  // Every row follows the rule: side by side when the label, the gap, and the answer fit across the row,
  // and wrapped when they don't. Fonts render a little differently on each computer, so a pair within
  // 2px of fitting can go either way and isn't checked.
  const rows = await page.locator("section.setting-row .row-text").evaluateAll((all) =>
    all.map((text) => {
      const width = (el: Element) => {
        const range = document.createRange();
        range.selectNodeContents(el);
        return range.getBoundingClientRect().width;
      };
      const label = text.querySelector("h3")!;
      const value = text.querySelector(".row-value")!;
      const [l, v] = [label.getBoundingClientRect(), value.getBoundingClientRect()];
      return {
        name: label.textContent,
        room: text.getBoundingClientRect().width - (width(label) + 16 + width(value)),
        beside: v.left >= l.right - 1 && v.top < l.bottom && l.top < v.bottom,
      };
    }),
  );
  for (const r of rows) {
    if (r.room > 2) expect(r.beside, `${r.name} fits, so it shares the line`).toBe(true);
    if (r.room < -2) expect(r.beside, `${r.name} doesn't fit, so it wraps`).toBe(false);
  }

  // While editing, the label and its box share a line on desktop. A phone has no room, so the box goes under it.
  await openEditor(page, "Edit arrive before iqamah");
  const editing = await sideBySide(page, `${row("Arrive before iqamah")} .inline-field label`, `${row("Arrive before iqamah")} .minutes-field`);
  expect(editing).toBe(info.project.name === "desktop");

  // Nothing ever runs off the screen.
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});

test("the 2 notification dropdowns save, show, and stay after a reload", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");
  // The highlight shows on this page too.
  await expect(page.locator("mark.highlight")).toHaveText("every 5 minutes");
  // Masjid prayers have no notification of their own.
  await expect(page.getByRole("region", { name: /iqamah/ }).filter({ hasText: "otif" })).toHaveCount(0);
  await expect(page.getByText(/notif\w* before iqamah/i)).toHaveCount(0);

  const rows = {
    leave: { name: "Notify before leaving", question: "Notify before leaving", start: "5 minutes", pick: "30 minutes" },
    home: { name: "Notify before home prayers", question: "Notify before home prayers", start: "5 minutes", pick: "15 minutes" },
  };
  for (const row of Object.values(rows)) {
    const region = page.getByRole("region", { name: row.name });
    // The defaults: 5 minutes before leaving and before home prayers.
    await expect(region.locator("h3")).toHaveText(row.question);
    await expect(region.locator(".row-value")).toHaveText(row.start);
    await openEditor(page, `Edit ${row.name.toLowerCase()}`);
    const select = region.getByRole("combobox", { name: row.question });
    await expect(select.locator("option")).toHaveText(["No notification", "5 minutes", "10 minutes", "15 minutes", "20 minutes", "30 minutes"]);
    await select.selectOption({ label: row.pick });
    await region.getByRole("button", { name: "Save" }).click();
    await expect(region.locator(".row-value")).toHaveText(row.pick);
  }
  const lastSave = () => api.calls("PUT", "/api/settings/optional").at(-1)!.body as Record<string, number | null>;
  const sent = lastSave();
  expect([sent.leave_reminder_minutes, sent.home_reminder_minutes]).toEqual([30, 15]);
  expect(sent).not.toHaveProperty("masjid_reminder_minutes");

  // Saving another optional setting keeps the notifications.
  await openEditor(page, "Edit arrive before iqamah");
  await page.getByRole("spinbutton", { name: "Arrive before iqamah" }).fill("7");
  await page.getByRole("region", { name: "Arrive before iqamah" }).getByRole("button", { name: "Save" }).click();
  const after = lastSave();
  expect([after.leave_reminder_minutes, after.home_reminder_minutes]).toEqual([30, 15]);

  await page.reload();
  for (const row of Object.values(rows)) {
    await expect(page.getByRole("region", { name: row.name }).locator(".row-value")).toHaveText(row.pick);
  }

  // Back to "No notification" sends null, not 0.
  await openEditor(page, "Edit notify before home prayers");
  await page.getByRole("combobox", { name: rows.home.question }).selectOption({ label: "No notification" });
  await page.getByRole("region", { name: rows.home.name }).getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("region", { name: rows.home.name }).locator(".row-value")).toHaveText("No notification");
  expect(lastSave().home_reminder_minutes).toBeNull();
});
