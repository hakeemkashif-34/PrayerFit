import { expect, test } from "@playwright/test";
import { finishedSettings, GOOGLE_CALENDAR, KMA, MockApi } from "./mock-api";

test("Settings has 2 cards, Required and Optional, each item with its own Edit", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByText("Signed in as hakeem@example.com")).toBeVisible();
  const required = page.getByRole("region", { name: "Required" });
  const optional = page.getByRole("region", { name: "Optional" });
  for (const name of ["Location", "Main masjid", "Prayers at the masjid", "Jumuah pick"]) {
    await expect(required.getByRole("region", { name })).toBeVisible();
  }
  const optionalItems = [
    "Short name", "How early for prayers", "How early for Jumuah",
    "Prayer colour", "Drive colour",
  ];
  for (const name of optionalItems) {
    await expect(optional.getByRole("region", { name })).toBeVisible();
  }
  for (const name of ["Location", "Main masjid", "Prayers at the masjid", "Jumuah pick", ...optionalItems]) {
    await expect(page.getByRole("button", { name: `Edit ${name.toLowerCase()}` })).toBeVisible();
  }
  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  await expect(page.getByText("Saturday: all at home")).toBeVisible();
  // Where each masjid's times come from.
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("Times from MAWAQIT, updated Oct 25, 2026");
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("KMA");
  // The setup question as the label, and just the answer as the value.
  const early = page.getByRole("region", { name: "How early for prayers" });
  await expect(early.locator("h3")).toHaveText("How early do you want to arrive before iqamah (daily prayers)?");
  await expect(early.locator(".row-value")).toHaveText("5 minutes");
  const jumuahEarly = page.getByRole("region", { name: "How early for Jumuah" });
  await expect(jumuahEarly.locator("h3")).toHaveText("How early do you want to arrive before Jumuah (Friday prayer)?");
  await expect(jumuahEarly.locator(".row-value")).toHaveText("10 minutes");
  await expect(page.getByText(/Arrive \d+ min/)).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Location" }).locator("h3")).toHaveText("What's your location?");
  await expect(page.getByRole("region", { name: "Main masjid" }).locator("h3")).toHaveText("Which masjid do you usually go to?");
  await expect(page.getByRole("region", { name: "Prayers at the masjid" }).locator("h3")).toHaveText(
    "Which prayers do you usually pray at the masjid?",
  );
  await expect(page.getByRole("region", { name: "Jumuah pick" }).locator("h3")).toHaveText(
    "Generally speaking, which Jumuah would you like to attend?",
  );
  // Jumuah is always at the main masjid, so there's no Jumuah masjids setting.
  await expect(page.getByRole("region", { name: "Jumuah masjids" })).toHaveCount(0);
  // How often the calendar catches up.
  await expect(page.getByText("Updates and changes are reflected on your calendar every 5 minutes.")).toBeVisible();
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

  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();
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

  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toContainText("Saved. Sign in again so your calendar can update.");
  await expect(page.getByRole("status").getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
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
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("KMA");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await expect(page.getByRole("textbox", { name: /Short name/ })).toHaveCount(0);
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({
    choice: "masjid", masjid_id: "22222222-2222-2222-2222-222222222222",
  });
  await expect(page.getByRole("region", { name: "Short name" })).toContainText("None");
  await page.getByRole("button", { name: "Edit short name" }).click();
  await expect(page.getByLabel("Short name for Stittsville Masjid")).toHaveValue("");
});

// What finishedSettings() has saved for the optional answers.
const SAVED_OPTIONAL = {
  arrive_early_minutes: 5, jumuah_arrive_early_minutes: 10, short_name: "KMA", prayer_color_id: "7", drive_color_id: null,
};

test("how early for prayers is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit how early for prayers" }).click();
  const early = page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?");
  await expect(early).toHaveValue("5");
  await early.fill("45");
  await page.getByRole("button", { name: "Save" }).click();

  // Every other answer is sent as it was saved.
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, arrive_early_minutes: 45 });
  await expect(page.getByRole("region", { name: "How early for prayers" }).locator(".row-value")).toHaveText("45 minutes");
  await expect(page.getByRole("region", { name: "How early for Jumuah" }).locator(".row-value")).toHaveText("10 minutes");
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 20 events sent to Google.");
});

test("how early for Jumuah is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit how early for jumuah" }).click();
  await page.getByLabel("How early do you want to arrive before Jumuah (Friday prayer)?").fill("0");
  await page.getByRole("button", { name: "Save" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, jumuah_arrive_early_minutes: 0 });
  await expect(page.getByRole("region", { name: "How early for Jumuah" }).locator(".row-value")).toHaveText("0 minutes");
});

test("the short name is edited on its own", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit short name" }).click();
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

  await page.getByRole("button", { name: "Edit prayer colour" }).click();
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Peacock");
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  await page.getByRole("option", { name: "Calendar colour" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({ ...SAVED_OPTIONAL, prayer_color_id: null });
  await expect(page.getByRole("region", { name: "Prayer colour" })).toContainText("Calendar colour");

  await page.getByRole("button", { name: "Edit drive colour" }).click();
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

  await page.getByRole("button", { name: "Edit how early for prayers" }).click();
  await page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?").fill("0");
  await page.getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByRole("region", { name: "How early for prayers" }).locator(".row-value")).toHaveText("5 minutes");
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
});

test("only one item is edited at a time", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit short name" }).click();
  await expect(page.getByRole("button", { name: "Edit location" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Edit prayer colour" })).toBeDisabled();
});

test("a new main masjid moves Jumuah there too, starting at its 1st Jumuah", async ({ page }) => {
  const api = new MockApi().signedIn({ ...finishedSettings(), jumuah_pick: { masjid_id: KMA.id, order: 2 } });
  await api.install(page);
  await page.goto("/");
  const pick = page.getByRole("region", { name: "Jumuah pick" });
  await expect(pick.locator(".row-value")).toHaveText("2nd Jumuah");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
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

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("button", { name: "I pray at home" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "home" });
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("I pray at home");
  await expect(page.getByRole("region", { name: "Prayers at the masjid" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Short name" })).toHaveCount(0);
  // Praying at home means no Jumuah.
  await expect(page.getByRole("region", { name: "Jumuah pick" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "How early for Jumuah" })).toHaveCount(0);
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
  await expect(page.getByRole("region", { name: "How early for prayers" }).locator(".row-value")).toHaveText("0 minutes");
  await expect(page.getByRole("region", { name: "Prayer colour" })).toContainText("Calendar colour");

  await page.getByRole("button", { name: "Edit how early for prayers" }).click();
  await expect(page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?")).toHaveValue("0");
  await page.getByRole("button", { name: "Cancel" }).click();
  await page.getByRole("button", { name: "Edit drive colour" }).click();
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toContainText("Calendar colour");
});

test("a bad how early number on the Settings page shows the error and saves nothing", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  for (const [button, label] of [
    ["Edit how early for prayers", "How early do you want to arrive before iqamah (daily prayers)?"],
    ["Edit how early for jumuah", "How early do you want to arrive before Jumuah (Friday prayer)?"],
  ]) {
    await page.getByRole("button", { name: button }).click();
    await page.getByLabel(label).fill("61");
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
  await expect(row.locator("h3")).toHaveText("What's your location?");
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
  await page.getByRole("button", { name: "Edit location" }).click();
  expect(await easing()).toBeGreaterThan(0);
  await page.waitForTimeout(400);
  await row.getByRole("button", { name: "Cancel" }).click();
  expect(await easing()).toBeGreaterThan(0);

  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForTimeout(400);
  await page.getByRole("button", { name: "Edit location" }).click();
  expect(await easing()).toBe(0);
});


test("a notice at the top says when a masjid's times couldn't be confirmed", async ({ page }) => {
  const notice = "KMA's times couldn't be confirmed since Oct 24, 2026. Your calendar is using calculated times until they're back.";
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
  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();
  await page.getByRole("button", { name: "Save" }).click();
  await expect(page.getByRole("status")).toHaveText(/^Calendar updated/);
  const background = (selector: string) =>
    page.locator(selector).evaluate((el) => getComputedStyle(el).backgroundColor);
  // White, which stands out on the light green page.
  expect(await background(".settings-card.required")).toBe("rgb(255, 255, 255)");
  expect(await background(".settings-card.optional")).toBe("rgb(255, 255, 255)");
  expect(await page.getByRole("status").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgb(255, 255, 255)");
});
