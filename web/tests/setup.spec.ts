import { expect, test, type Page } from "@playwright/test";
import { GOOGLE_CALENDAR, HOME_PLACE, KMA, MockApi } from "./mock-api";

const LOCATION = "What's your location?";
const MASJID = "Which masjid do you usually go to?";
const OPTIONAL = "A few extras";
const STEP_NAMES = ["Location", "Masjid", "Weekly prayers", "Optional"];

// The current step is highlighted in the list on a computer, and named in
// one line at the top on a phone.
async function expectStep(page: Page, number: number) {
  await expect(page.locator('[aria-current="step"]')).toContainText(STEP_NAMES[number - 1]);
  const phoneLine = page.getByText(`Setup · Step ${number} of 4`);
  if (test.info().project.name === "phone") await expect(phoneLine).toBeVisible();
  else await expect(page.getByRole("complementary", { name: "Setup steps" })).toBeVisible();
}

async function pickMasjid(page: Page, typed: string, name: string) {
  await page.getByRole("combobox").pressSequentially(typed, { delay: 30 });
  await page.getByRole("option", { name: new RegExp(`^${name}`) }).click();
}

// Finishing setup sends the user to Google Calendar, faked by the mock API.
async function expectGoogleCalendar(page: Page, api: MockApi) {
  await expect(page).toHaveURL(GOOGLE_CALENDAR);
  await expect(page.getByRole("heading", { name: "Fake Google Calendar" })).toBeVisible();
  expect(api.googleVisits).toEqual([GOOGLE_CALENDAR]);
}

async function pickColour(page: Page, picker: string, colour: string) {
  await page.getByRole("button", { name: new RegExp(`^${picker}`) }).click();
  await page.getByRole("option", { name: colour }).click();
}

async function pickHome(page: Page) {
  await page.getByRole("combobox").pressSequentially("200 Kanata", { delay: 30 });
  await page.getByRole("option", { name: HOME_PLACE }).click();
  // Wait for the masjid question, so the next typing goes into its box,
  // not the location box that's still on screen while the location saves.
  await expect(page.getByRole("heading", { level: 1, name: MASJID })).toBeVisible();
}

test("the full setup: location, masjid, weekly grid, extras, then a filled calendar", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  // 1. Location, with suggestions as the user types.
  await expect(page.getByRole("heading", { level: 1, name: LOCATION })).toBeVisible();
  await expectStep(page, 1);
  await expect(page.getByRole("button", { name: "← Back" })).toHaveCount(0);
  // Just the question: no extra lines, and the credit is in the footer.
  await expect(page.getByText("Your address is stored encrypted")).toHaveCount(0);
  await expect(page.getByText("Prayer times depend on where you are")).toHaveCount(0);
  await expect(page.getByRole("main").getByText("OpenStreetMap contributors")).toHaveCount(0);
  await expect(page.getByRole("contentinfo").getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();

  // Fewer than 3 characters never searches.
  const box = page.getByRole("combobox");
  await box.pressSequentially("20", { delay: 30 });
  await page.waitForTimeout(600);
  expect(api.calls("POST", "/api/setup/location/suggest")).toHaveLength(0);

  // Typing quickly sends one search, after the pause, for the whole text.
  await box.pressSequentially("0 Kanata", { delay: 30 });
  const options = page.getByRole("option");
  await expect(options).toHaveText([HOME_PLACE, "200 Kanata Avenue, Rochester, New York, United States"]);
  expect((await api.sent("POST", "/api/setup/location/suggest")).map((c) => c.body)).toEqual([{ query: "200 Kanata" }]);

  await options.first().click();
  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "200 Kanata", index: 0 });

  // 2. Masjid: a search box like the location step, closest first, with distances.
  await expect(page.getByRole("heading", { level: 1, name: MASJID })).toBeVisible();
  await expectStep(page, 2);
  await expect(page.getByText("Can't find it? Type its address.")).toBeVisible();
  await expect(page.getByRole("radio")).toHaveCount(0); // no list to choose from any more
  await expect(page.getByRole("button", { name: "Skip" })).toBeVisible();
  const masjidBox = page.getByRole("combobox");
  await masjidBox.pressSequentially("Kanata", { delay: 30 });
  await expect(page.getByRole("option")).toHaveText([
    /^Kanata Muslim Association1\.1 km away · 351 Sandhill Rd/,
    /^Kanata Masjid Toronto352\.1 km away/,
  ]);
  expect((await api.sent("POST", "/api/setup/masjid/suggest")).map((c) => c.body)).toEqual([{ query: "Kanata" }]);
  await page.getByRole("option", { name: /^Kanata Muslim Association/ }).click();
  expect((await api.sent("POST", "/api/masjids/from-suggestion", 1))[0].body).toEqual({ query: "Kanata", index: 0 });
  await expect(page.locator(".picked-masjid")).toContainText("Kanata Muslim Association · 1.1 km away");
  // The short name moved to the optional step.
  await expect(page.getByLabel(/Short name/)).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "masjid", masjid_id: KMA.id });

  // 3. Weekly grid: prayers are rows, days are columns.
  await expect(page.getByRole("heading", { level: 1, name: "Which prayers do you usually pray at Kanata Muslim Association?" })).toBeVisible();
  await expectStep(page, 3);
  await expect(page.locator("table.grid thead th")).toHaveText(["Prayer", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  await expect(page.locator("table.grid tbody th")).toHaveText(["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]);
  await expect(page.getByRole("checkbox")).toHaveCount(35);
  await page.getByLabel("Dhuhr on Monday at the masjid").check();
  await page.getByLabel("Isha on Friday at the masjid").check();
  await page.getByLabel("Fajr on Sunday at the masjid").check();
  await page.getByRole("button", { name: "Next" }).click();

  const days = ((await api.sent("PUT", "/api/settings/weekly", 1))[0].body as { days: Record<string, unknown>[] }).days;
  expect(days).toHaveLength(7);
  expect(days[0]).toEqual({ weekday: 0, fajr: false, dhuhr: true, asr: false, maghrib: false, isha: false });
  expect(days[4].isha).toBe(true);
  expect(days[6].fajr).toBe(true);

  // 4. Optional: how early, short name, and colours. Each has a default.
  await expect(page.getByRole("heading", { level: 1, name: OPTIONAL })).toBeVisible();
  await expectStep(page, 4);
  await expect(page.getByRole("button", { name: "Skip" })).toBeVisible();
  // Nothing has gone to Google yet: the first calendar update comes after this step.
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
  expect(api.googleVisits).toEqual([]);
  // A number box, pre-filled with the default: 5 minutes.
  const early = page.getByLabel("How early do you want to arrive before iqamah?");
  await expect(early).toHaveAttribute("type", "number");
  await expect(early).toHaveValue("5");
  await early.fill("10");
  await page.getByLabel("Short name for Kanata Muslim Association").fill("KMA");
  await expect(page.getByText('Events will say "Dhuhr at KMA".')).toBeVisible();
  // Both colours start as Basil, Google's green.
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Basil");
  await expect(page.getByRole("button", { name: /^Commute colour/ })).toContainText("Basil");
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  // Every Google colour, by Google's name, after "Calendar colour".
  await expect(page.getByRole("listbox").getByRole("option")).toHaveText([
    "Calendar colour", "Tomato", "Flamingo", "Tangerine", "Banana", "Sage", "Basil",
    "Peacock", "Blueberry", "Lavender", "Grape", "Graphite",
  ]);
  // Like Google's menu: a tick on the chosen one, Basil by default.
  await expect(page.getByRole("listbox").getByRole("option", { selected: true })).toHaveText("Basil");
  await expect(page.locator(".colour-list .tick")).toHaveCount(1);
  await expect(page.getByRole("option", { name: "Basil" }).locator(".tick")).toBeVisible();
  await page.getByRole("option", { name: "Peacock" }).click();
  await pickColour(page, "Commute colour", "Tomato");
  await expect(page.getByRole("button", { name: /^Commute colour/ })).toContainText("Tomato");
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({
    arrive_early_minutes: 10, short_name: "KMA", prayer_color_id: "7", drive_color_id: "11",
  });

  // Finishing fills the calendar straight away, then opens Google Calendar
  // in the same tab, for the account they signed in with. No methods or Jumuah questions.
  await expectGoogleCalendar(page, api);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
  expect(api.calls("PUT", "/api/settings/methods")).toHaveLength(0);
  expect(api.calls("PUT", "/api/settings/jumuah")).toHaveLength(0);
});

test("Back goes to the previous question with the answer kept", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await pickHome(page);
  await pickMasjid(page, "Stittsville", "Stittsville Masjid");
  await page.getByRole("button", { name: "Next" }).click();
  await expectStep(page, 3);

  await page.getByRole("button", { name: "← Back" }).click();
  await expect(page.getByRole("heading", { level: 1, name: MASJID })).toBeVisible();
  await expect(page.locator(".picked-masjid")).toContainText("Stittsville Masjid");

  await page.getByRole("button", { name: "← Back" }).click();
  await expect(page.getByRole("heading", { level: 1, name: LOCATION })).toBeVisible();
  await expect(page.getByText(`Saved: ${HOME_PLACE}`)).toBeVisible();

  // Next keeps the saved location without saving it again.
  await page.getByRole("button", { name: "Next" }).click();
  await expectStep(page, 2);
  expect(api.calls("PUT", "/api/settings/location")).toHaveLength(1);
});

test("the arrow keys and Enter pick a suggestion", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await page.getByRole("combobox").pressSequentially("200 Kanata", { delay: 30 });
  await expect(page.getByRole("option")).toHaveCount(2);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");

  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "200 Kanata", index: 1 });
});

test("no match says so", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  await page.getByRole("combobox").pressSequentially("nowhere at all", { delay: 20 });

  await expect(page.getByText("No places found. Try adding the city.")).toBeVisible();
});

test("Skip means every prayer at home, with no weekly grid", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();

  // Straight to the optional step, with no weekly grid and no short name.
  await expect(page.getByRole("heading", { level: 1, name: OPTIONAL })).toBeVisible();
  await expectStep(page, 4);
  await expect(page.getByLabel(/Short name/)).toHaveCount(0);
  // Back goes to the masjid question, since the grid was skipped.
  await page.getByRole("button", { name: "← Back" }).click();
  await expect(page.getByRole("heading", { level: 1, name: MASJID })).toBeVisible();
  await page.getByRole("button", { name: "Skip" }).click();
  await page.getByRole("button", { name: "Skip" }).click();

  await expectGoogleCalendar(page, api);
  expect(api.settings.main_masjid_choice).toBe("home");
  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "home" });
  expect(api.calls("PUT", "/api/settings/weekly")).toHaveLength(0);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
});

test("a masjid that isn't on the map can be picked by typing its address", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await pickHome(page);
  await page.getByRole("combobox").pressSequentially("3500 Fallowfield", { delay: 30 });
  await expect(page.getByRole("option")).toHaveText([/^3500 Fallowfield Road, Ottawa, Ontario, CanadaAddress · 7\.2 km away/]);
  await page.getByRole("option").first().click();

  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({
    choice: "masjid", masjid_id: "44444444-4444-4444-4444-444444444444",
  });
  await expect(page.getByRole("heading", { level: 1, name: "Which prayers do you usually pray at your masjid?" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  // No name on the map, so the optional step asks for one.
  await expect(page.getByText("This masjid has no name on the map.")).toBeVisible();
  await page.getByLabel("Short name for your masjid").fill("Barrhaven Musalla");
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toMatchObject({ short_name: "Barrhaven Musalla" });
  await expectGoogleCalendar(page, api);
  expect(api.settings.main_masjid_short_name).toBe("Barrhaven Musalla");
});

test("the masjid search waits for a typing pause and 3 characters", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);

  const box = page.getByRole("combobox");
  await box.pressSequentially("Ka", { delay: 30 });
  await page.waitForTimeout(600);
  expect(api.calls("POST", "/api/setup/masjid/suggest")).toHaveLength(0);

  await box.pressSequentially("nata Muslim", { delay: 30 });
  await expect(page.getByRole("option")).toHaveCount(1);
  expect((await api.sent("POST", "/api/setup/masjid/suggest")).map((c) => c.body)).toEqual([{ query: "Kanata Muslim" }]);
});

test("Change goes back to the masjid search box", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");

  await page.getByRole("button", { name: "Change" }).click();
  await pickMasjid(page, "Stittsville", "Stittsville Masjid");

  await expect(page.locator(".picked-masjid")).toContainText("Stittsville Masjid · 5.8 km away");
});

test("a failed masjid search shows its message and Skip still works", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/masjid/suggest"] = { status: 503, detail: { message: "The search is busy. Try again in a minute." } };
  await api.install(page);
  await page.goto("/");
  await pickHome(page);

  await page.getByRole("combobox").pressSequentially("Kanata", { delay: 30 });
  await expect(page.getByRole("alert")).toHaveText("The search is busy. Try again in a minute.");
  await page.getByRole("button", { name: "Skip" }).click();
  await expect(page.getByRole("heading", { level: 1, name: OPTIONAL })).toBeVisible();
});

test("ticking nothing in the grid means every prayer at home", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { level: 1, name: /Which prayers/ })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();

  const days = ((await api.sent("PUT", "/api/settings/weekly", 1))[0].body as { days: Record<string, boolean>[] }).days;
  expect(days.every((d) => !d.fajr && !d.dhuhr && !d.asr && !d.maghrib && !d.isha)).toBe(true);
  await expect(page.getByRole("heading", { level: 1, name: OPTIONAL })).toBeVisible();
});

test("a busy address search shows its message", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/location/suggest"] = {
    status: 503,
    detail: { message: "The address search is busy. Try again in a minute." },
  };
  await api.install(page);
  await page.goto("/");

  await page.getByRole("combobox").pressSequentially("200 Kanata", { delay: 30 });

  await expect(page.getByRole("alert")).toHaveText("The address search is busy. Try again in a minute.");
});

test("answers saved before but never finished fill the calendar on the next visit", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.settings = { ...api.settings, address: HOME_PLACE, place_name: HOME_PLACE, time_zone: "America/Toronto", main_masjid_choice: "home" };
  api.optionalSaved = true;
  await api.install(page);
  await page.goto("/");

  await expectGoogleCalendar(page, api);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
});

test("setup looks like the landing page: steps on the left on a computer, one line on a phone", async ({ page }, info) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  const steps = page.getByRole("complementary", { name: "Setup steps" });
  const question = page.getByRole("heading", { level: 1, name: LOCATION });
  await expect(question).toBeVisible();
  if (info.project.name === "phone") {
    await expect(steps).toBeHidden();
    await expect(page.getByText("Setup · Step 1 of 4")).toBeVisible();
  } else {
    await expect(steps.getByRole("heading", { name: "Setup" })).toBeVisible();
    await expect(steps.getByRole("listitem")).toHaveText([/Location/, /Masjid/, /Weekly prayers/, /Optional/]);
    await expect(steps.locator('[aria-current="step"]')).toHaveText(/Location/);
    await expect(page.getByText("Setup · Step 1 of 4")).toBeHidden();
    const left = await steps.boundingBox();
    const right = await question.boundingBox();
    expect(right!.x).toBeGreaterThan(left!.x + left!.width - 1);
  }
});

test("suggestions never show postal codes", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  await page.getByRole("combobox").pressSequentially("200 Kanata", { delay: 30 });

  await expect(page.getByRole("option").first()).toHaveText(HOME_PLACE);
  await expect(page.getByRole("listbox")).not.toContainText("K2T");
});

test("the page uses Plus Jakarta Sans from our own site", async ({ page }) => {
  const fontRequests: string[] = [];
  page.on("request", (r) => {
    if (r.url().includes(".woff2")) fontRequests.push(r.url());
  });
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: LOCATION })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  const family = await page.getByRole("heading", { level: 1 }).evaluate((h) => getComputedStyle(h).fontFamily);
  expect(family).toContain("Plus Jakarta Sans");
  expect(await page.evaluate(() => document.fonts.check('16px "Plus Jakarta Sans Variable"'))).toBe(true);
  expect(fontRequests.length).toBeGreaterThan(0);
  expect(fontRequests.every((url) => url.startsWith("http://localhost:4173/assets/"))).toBe(true);
});

test("the optional step can be skipped, which saves the defaults", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByLabel("Isha on Monday at the masjid").check();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("heading", { level: 1, name: OPTIONAL })).toBeVisible();
  // Something typed, then skipped: the defaults win.
  await page.getByLabel("How early do you want to arrive before iqamah?").fill("20");
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
  await page.getByRole("button", { name: "Skip" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({
    arrive_early_minutes: 5, prayer_color_id: "10", drive_color_id: "10",
  });
  await expectGoogleCalendar(page, api);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
  expect(api.settings.arrive_early_minutes).toBe(5);
  expect([api.settings.prayer_color_id, api.settings.drive_color_id]).toEqual(["10", "10"]);
});

test("the colour dropdown works with the keyboard", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();

  const button = page.getByRole("button", { name: /^Commute colour/ });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("listbox")).toBeVisible();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  // From Basil, 2 down is Blueberry.
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(button).toContainText("Blueberry");
  await expect(button).toBeFocused();
  await page.keyboard.press("ArrowDown");
  // The tick moved to the new choice.
  await expect(page.getByRole("listbox").getByRole("option", { selected: true })).toHaveText("Blueberry");
  await expect(page.getByRole("option", { name: "Blueberry" }).locator(".tick")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("listbox")).toHaveCount(0);
  await expect(button).toContainText("Blueberry");
});

test("finishing shows a message until the calendar is filled, then opens Google Calendar", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.finishDelayMs = 1500;
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();
  await page.getByRole("button", { name: "Finish" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Adding your prayers to Google Calendar..." })).toBeVisible();
  expect(api.googleVisits).toEqual([]);
  await expectGoogleCalendar(page, api);
});

test("if the first calendar update fails, it stays on our site and shows why", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.finishCalendar = {
    status: "waiting", sent: 40, waiting: 30,
    message: "Saved. Some prayers haven't reached Google Calendar yet. Try again in a minute.",
  };
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();
  await page.getByRole("button", { name: "Skip" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Some prayers haven't reached Google Calendar yet.");
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(api.googleVisits).toEqual([]);
  expect(page.url()).not.toContain("google.com");
});

test("if finishing setup fails, it stays on the setup page with the error", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/finish"] = { status: 503, detail: { message: "Google Calendar didn't answer. Try again in a minute." } };
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();
  await page.getByRole("button", { name: "Skip" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Something went wrong" })).toBeVisible();
  await expect(page.getByRole("alert")).toHaveText("Google Calendar didn't answer. Try again in a minute.");
  expect(api.googleVisits).toEqual([]);

  // Try again works, and then it opens Google Calendar.
  await page.getByRole("button", { name: "Try again" }).click();
  await expectGoogleCalendar(page, api);
});

test("how early takes whole numbers from 0 to 60 only", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();

  const early = page.getByLabel("How early do you want to arrive before iqamah?");
  for (const bad of ["61", "-1", "2.5", "", "100"]) {
    await early.fill(bad);
    await page.getByRole("button", { name: "Finish" }).click();
    await expect(page.getByRole("alert")).toHaveText("Enter a whole number of minutes from 0 to 60.");
    await expect(early).toHaveAttribute("aria-invalid", "true");
  }
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);

  // 60 is the most allowed. (0 is in the next test.)
  await early.fill("60");
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toMatchObject({ arrive_early_minutes: 60 });
  await expectGoogleCalendar(page, api);
});

test("0 minutes early is allowed", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await page.getByRole("button", { name: "Skip" }).click();

  await page.getByLabel("How early do you want to arrive before iqamah?").fill("0");
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toMatchObject({ arrive_early_minutes: 0 });
  await expectGoogleCalendar(page, api);
});

test("the extras step: short text, Commute colour, and Skip in the top-right corner", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: "Next" }).click();

  const heading = page.getByRole("heading", { level: 1, name: OPTIONAL });
  await expect(heading).toBeVisible();
  // The removed lines stay gone. The error message for a wrong number stays (tested above).
  for (const gone of ["All optional", "The drive block before each masjid prayer", "Google Calendar's own colours", "(optional)"]) {
    await expect(page.getByText(gone)).toHaveCount(0);
  }
  await expect(page.getByLabel("Short name for Kanata Muslim Association", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Commute colour/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toHaveCount(0);

  // Skip is level with the heading, at the right edge of the step.
  const skip = page.getByRole("button", { name: "Skip" });
  const finish = page.getByRole("button", { name: "Finish" });
  const [skipBox, headingBox, finishBox, form] = await Promise.all([
    skip.boundingBox(), heading.boundingBox(), finish.boundingBox(), page.locator("form").boundingBox(),
  ]);
  expect(skipBox!.y).toBeLessThan(headingBox!.y + headingBox!.height);
  expect(skipBox!.y + skipBox!.height).toBeGreaterThan(headingBox!.y);
  expect(skipBox!.x + skipBox!.width).toBeGreaterThan(form!.x + form!.width - 2);
  expect(skipBox!.y).toBeLessThan(finishBox!.y);
});
