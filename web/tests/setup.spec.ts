import { expect, test, type Page } from "@playwright/test";
import { GOOGLE_CALENDAR, HOME_PLACE, KMA, MockApi } from "./mock-api";

const LOCATION = "What's your location?";
const MASJID = "Which masjid do you usually go to?";
const PAGE_NAMES = ["Required", "Optional"];

// The current page is highlighted in the list on a computer, and named in
// one line at the top on a phone.
async function expectPage(page: Page, number: number) {
  await expect(page.getByRole("heading", { level: 1, name: PAGE_NAMES[number - 1] })).toBeVisible();
  await expect(page.locator('[aria-current="step"]')).toContainText(PAGE_NAMES[number - 1]);
  const phoneLine = page.getByText(`Setup · Step ${number} of 2`);
  if (test.info().project.name === "phone") await expect(phoneLine).toBeVisible();
  else await expect(page.getByRole("complementary", { name: "Setup steps" })).toBeVisible();
}

const addressBox = (page: Page) => page.getByRole("combobox", { name: "Address" });
const masjidBox = (page: Page) => page.getByRole("combobox", { name: "Masjid" });

async function pickMasjid(page: Page, typed: string, name: string) {
  await masjidBox(page).pressSequentially(typed, { delay: 30 });
  await page.getByRole("option", { name: new RegExp(`^${name}`) }).click();
}

// The tab that Finish opened. Every test has one browser context of its own.
async function newTab(page: Page): Promise<Page> {
  await expect.poll(() => page.context().pages().length).toBe(2);
  return page.context().pages().find((p) => p !== page)!;
}

// Finish opened a new tab, which goes to Google Calendar (faked by the mock
// API). This tab goes to Settings and stays on our site.
async function expectGoogleCalendar(page: Page, api: MockApi) {
  const tab = await newTab(page);
  await expect(tab).toHaveURL(GOOGLE_CALENDAR);
  await expect(tab.getByRole("heading", { name: "Fake Google Calendar" })).toBeVisible();
  expect(api.googleVisits).toEqual([GOOGLE_CALENDAR]);
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  expect(new URL(page.url()).host).toBe("localhost:4173");
}

async function pickColour(page: Page, picker: string, colour: string) {
  await page.getByRole("button", { name: new RegExp(`^${picker}`) }).click();
  await page.getByRole("option", { name: colour }).click();
}

async function pickHome(page: Page) {
  await addressBox(page).pressSequentially("200 Kanata", { delay: 30 });
  await page.getByRole("option", { name: HOME_PLACE }).click();
  // Wait for the masjid search, which needs the location saved first.
  await expect(masjidBox(page)).toBeEnabled();
}

// Page 1 answered with "I pray at home", then on to page 2.
async function toOptionalAtHome(page: Page) {
  await pickHome(page);
  await page.getByRole("button", { name: "I pray at home" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expectPage(page, 2);
}

// Page 1 answered with KMA and an empty grid, then on to page 2.
async function toOptionalAtKma(page: Page) {
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");
  await page.getByRole("button", { name: "Next" }).click();
  await expectPage(page, 2);
}

test("the full setup: required page, optional page, then a filled calendar", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  // Page 1: every question at once, top to bottom: location, masjid, and the weekly grid.
  await expectPage(page, 1);
  const questions = page.getByRole("main").getByRole("heading", { level: 2 });
  await expect(questions).toHaveText([LOCATION, MASJID, "Which prayers do you usually pray at your masjid?"]);
  const tops = await questions.evaluateAll((hs) => hs.map((h) => h.getBoundingClientRect().top));
  expect(tops).toEqual([...tops].sort((a, b) => a - b));
  await expect(page.getByRole("checkbox")).toHaveCount(35);
  // An example under each of the first 2 questions.
  await expect(page.getByText("e.g. 24 Maple Drive, Ottawa")).toBeVisible();
  await expect(page.getByText("e.g. Kanata Muslim Association")).toBeVisible();
  await expect(page.getByRole("button", { name: "← Back" })).toHaveCount(0);
  // The masjid search is there, but waits for the location, since it sorts by distance from home.
  await expect(masjidBox(page)).toBeVisible();
  await expect(masjidBox(page)).toBeDisabled();
  await expect(page.getByText("Pick your location first")).toBeVisible();
  // Just the question: no extra lines, and the credit is in the footer.
  await expect(page.getByText("Your address is stored encrypted")).toHaveCount(0);
  await expect(page.getByRole("main").getByText("OpenStreetMap contributors")).toHaveCount(0);
  await expect(page.getByRole("contentinfo").getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();

  // Fewer than 3 characters never searches.
  await addressBox(page).pressSequentially("20", { delay: 30 });
  await page.waitForTimeout(600);
  expect(api.calls("POST", "/api/setup/location/suggest")).toHaveLength(0);

  // Typing quickly sends one search, after the pause, for the whole text.
  await addressBox(page).pressSequentially("0 Kanata", { delay: 30 });
  const options = page.getByRole("option");
  await expect(options).toHaveText([HOME_PLACE, "200 Kanata Avenue, Rochester, New York, United States"]);
  expect((await api.sent("POST", "/api/setup/location/suggest")).map((c) => c.body)).toEqual([{ query: "200 Kanata" }]);
  await options.first().click();
  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "200 Kanata", index: 0 });
  await expect(page.getByText(`Saved: ${HOME_PLACE}`)).toBeVisible();
  // Still on screen, so it's usable again once saved.
  await expect(page.getByText("Saving…")).toHaveCount(0);
  await expect(addressBox(page)).toBeEnabled();

  // Masjid: a search box, closest first, with distances.
  await expect(page.getByText("Can't find it? Type its address.")).toBeVisible();
  await expect(page.getByRole("button", { name: "I pray at home" })).toBeVisible();
  await masjidBox(page).pressSequentially("Kanata", { delay: 30 });
  await expect(page.getByRole("option")).toHaveText([
    /^Kanata Muslim Association1\.1 km away · 351 Sandhill Rd/,
    /^Kanata Masjid Toronto352\.1 km away/,
  ]);
  await page.getByRole("option", { name: /^Kanata Muslim Association/ }).click();
  await expect(page.locator(".picked-masjid")).toContainText("Kanata Muslim Association · 1.1 km away");

  // The weekly grid shows up once there's a masjid: prayers are rows, days are columns.
  await expect(page.getByRole("heading", { level: 2, name: "Which prayers do you usually pray at Kanata Muslim Association?" })).toBeVisible();
  await expect(page.locator("table.grid thead th")).toHaveText(["Prayer", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]);
  await expect(page.locator("table.grid tbody th")).toHaveText(["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]);
  await expect(page.getByRole("checkbox")).toHaveCount(35);
  await page.getByLabel("Dhuhr on Monday at the masjid").check();
  await page.getByLabel("Isha on Friday at the masjid").check();
  await page.getByLabel("Fajr on Sunday at the masjid").check();

  // Last on the page: which Jumuah, with the 1st Jumuah already picked.
  await expect(page.getByRole("main").getByRole("heading", { level: 2 }).last()).toHaveText(
    "Generally speaking, which Jumuah would you like to attend?",
  );
  await expect(page.getByRole("radio", { name: /^Kanata Muslim Association 1st Jumuah 1:30 PM to 2:15 PM/ })).toBeChecked();
  // Nothing about the masjid, grid, or Jumuah is saved until Next.
  expect(api.calls("PUT", "/api/settings/main-masjid")).toHaveLength(0);
  await page.getByRole("button", { name: "Next" }).click();

  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "masjid", masjid_id: KMA.id });
  const days = ((await api.sent("PUT", "/api/settings/weekly", 1))[0].body as { days: Record<string, unknown>[] }).days;
  expect(days).toHaveLength(7);
  expect((await api.sent("PUT", "/api/settings/jumuah-pick", 1))[0].body).toEqual({ masjid_id: KMA.id, order: 1 });
  expect(days[0]).toEqual({ weekday: 0, fajr: false, dhuhr: true, asr: false, maghrib: false, isha: false });
  expect(days[4].isha).toBe(true);
  expect(days[6].fajr).toBe(true);

  // Page 2: everything optional, each with a default, and Skip.
  await expectPage(page, 2);
  await expect(page.getByRole("button", { name: "Skip" })).toBeVisible();
  // Nothing has gone to Google yet: the first calendar update comes after this page.
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
  expect(api.googleVisits).toEqual([]);
  await page.getByLabel("Short name for Kanata Muslim Association").fill("KMA");
  await expect(page.getByText('Events will say "Dhuhr at KMA".')).toBeVisible();
  // Number boxes, pre-filled with the defaults: 5 minutes for each.
  const early = page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?");
  await expect(early).toHaveAttribute("type", "number");
  await expect(early).toHaveValue("5");
  await early.fill("10");
  const jumuahEarly = page.getByLabel("How early do you want to arrive before Jumuah (Friday prayer)?");
  await expect(jumuahEarly).toHaveValue("5");
  await jumuahEarly.fill("15");
  // Drive times always come from OpenRouteService, so there's no box for them.
  await expect(page.getByLabel(/Commute time|Drive time/)).toHaveCount(0);
  // Both colours start as Basil, Google's green.
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Basil");
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toContainText("Basil");
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
  await pickColour(page, "Drive colour", "Tomato");
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toContainText("Tomato");

  // The Jumuah question moved to page 1.
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Finish" }).click();

  // Finish saves the other answers, then finishes.
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({
    arrive_early_minutes: 10, jumuah_arrive_early_minutes: 15, short_name: "KMA", prayer_color_id: "7", drive_color_id: "11",
  });
  await expectGoogleCalendar(page, api);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
  expect(api.calls("PUT", "/api/settings/jumuah")).toHaveLength(0);
});

test("Back goes to page 1 without losing anything on either page", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Stittsville", "Stittsville Masjid");
  await page.getByLabel("Asr on Tuesday at the masjid").check();
  await page.getByRole("button", { name: "Next" }).click();
  await expectPage(page, 2);
  await page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?").fill("20");
  await page.getByLabel("Short name for Stittsville Masjid").fill("SM");
  await pickColour(page, "Prayer colour", "Grape");

  await page.getByRole("button", { name: "← Back" }).click();
  await expectPage(page, 1);
  await expect(page.getByText(`Saved: ${HOME_PLACE}`)).toBeVisible();
  await expect(page.locator(".picked-masjid")).toContainText("Stittsville Masjid");
  await expect(page.getByLabel("Asr on Tuesday at the masjid")).toBeChecked();

  // Next again: page 2 still has what was typed.
  await page.getByRole("button", { name: "Next" }).click();
  await expectPage(page, 2);
  await expect(page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?")).toHaveValue("20");
  await expect(page.getByLabel("Short name for Stittsville Masjid")).toHaveValue("SM");
  await expect(page.getByRole("button", { name: /^Prayer colour/ })).toContainText("Grape");
  // The location was only saved once. Nothing reached Google.
  expect(api.calls("PUT", "/api/settings/location")).toHaveLength(1);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
});

test("a different masjid after going Back gets its own short name", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);
  await page.getByLabel("Short name for Kanata Muslim Association").fill("KMA");

  await page.getByRole("button", { name: "← Back" }).click();
  await page.getByRole("button", { name: "Change" }).click();
  await pickMasjid(page, "Stittsville", "Stittsville Masjid");
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByLabel("Short name for Stittsville Masjid")).toHaveValue("");
});

test("Next asks for a location and a masjid first", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("alert")).toHaveText("Pick your location from the list.");
  await pickHome(page);
  await page.getByRole("button", { name: "Next" }).click();
  await expect(page.getByRole("alert")).toHaveText("Pick your masjid, or choose I pray at home.");
  expect(api.calls("PUT", "/api/settings/main-masjid")).toHaveLength(0);
});

test("the arrow keys and Enter pick a suggestion", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await addressBox(page).pressSequentially("200 Kanata", { delay: 30 });
  await expect(page.getByRole("option")).toHaveCount(2);
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");

  expect((await api.sent("PUT", "/api/settings/location", 1))[0].body).toEqual({ query: "200 Kanata", index: 1 });
});

test("no match says so", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  await addressBox(page).pressSequentially("nowhere at all", { delay: 20 });

  await expect(page.getByText("No places found. Try adding the city.")).toBeVisible();
});

test("I pray at home means every prayer at home, with no weekly grid", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await pickHome(page);
  await page.getByRole("button", { name: "I pray at home" }).click();
  await expect(page.locator(".picked-masjid")).toContainText("I pray at home");
  await expect(page.getByRole("checkbox")).toHaveCount(0);
  await page.getByRole("button", { name: "Next" }).click();

  // Page 2 has no short name, Jumuah how early, or chooser.
  await expectPage(page, 2);
  await expect(page.getByLabel(/Short name/)).toHaveCount(0);
  await expect(page.getByLabel(/before Jumuah/)).toHaveCount(0);
  await expect(page.getByRole("radio")).toHaveCount(0);
  await page.getByRole("button", { name: "Finish" }).click();

  await expectGoogleCalendar(page, api);
  expect(api.settings.main_masjid_choice).toBe("home");
  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({ choice: "home" });
  expect(api.calls("PUT", "/api/settings/weekly")).toHaveLength(0);
  // No Jumuah masjid, so there's no Jumuah to ask about or save.
  expect(api.calls("PUT", "/api/settings/jumuah-pick")).toHaveLength(0);
  expect(api.calls("GET", "/api/jumuah/slots")).toHaveLength(0);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
});

test("a masjid that isn't on the map can be picked by typing its address", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");

  await pickHome(page);
  await masjidBox(page).pressSequentially("3500 Fallowfield", { delay: 30 });
  await expect(page.getByRole("option")).toHaveText([/^3500 Fallowfield Road, Ottawa, Ontario, CanadaAddress · 7\.2 km away/]);
  await page.getByRole("option").first().click();
  await expect(page.getByRole("heading", { level: 2, name: "Which prayers do you usually pray at your masjid?" })).toBeVisible();
  await page.getByRole("button", { name: "Next" }).click();
  expect((await api.sent("PUT", "/api/settings/main-masjid", 1))[0].body).toEqual({
    choice: "masjid", masjid_id: "44444444-4444-4444-4444-444444444444",
  });

  // No name on the map, so page 2 asks for one.
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

  await masjidBox(page).pressSequentially("Ka", { delay: 30 });
  await page.waitForTimeout(600);
  expect(api.calls("POST", "/api/setup/masjid/suggest")).toHaveLength(0);

  await masjidBox(page).pressSequentially("nata Muslim", { delay: 30 });
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

test("a failed masjid search shows its message and I pray at home still works", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/masjid/suggest"] = { status: 503, detail: { message: "The search is busy. Try again in a minute." } };
  await api.install(page);
  await page.goto("/");
  await pickHome(page);

  await masjidBox(page).pressSequentially("Kanata", { delay: 30 });
  await expect(page.getByRole("alert")).toHaveText("The search is busy. Try again in a minute.");
  await page.getByRole("button", { name: "I pray at home" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await expectPage(page, 2);
});

test("ticking nothing in the grid means every prayer at home", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);

  const days = ((await api.sent("PUT", "/api/settings/weekly", 1))[0].body as { days: Record<string, boolean>[] }).days;
  expect(days.every((d) => !d.fajr && !d.dhuhr && !d.asr && !d.maghrib && !d.isha)).toBe(true);
});

test("a busy address search shows its message", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/location/suggest"] = {
    status: 503,
    detail: { message: "The address search is busy. Try again in a minute." },
  };
  await api.install(page);
  await page.goto("/");

  await addressBox(page).pressSequentially("200 Kanata", { delay: 30 });

  await expect(page.getByRole("alert")).toHaveText("The address search is busy. Try again in a minute.");
});

test("answers saved before but never finished fill the calendar on the next visit", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.settings = { ...api.settings, address: HOME_PLACE, place_name: HOME_PLACE, time_zone: "America/Toronto", main_masjid_choice: "home" };
  api.optionalSaved = true;
  await api.install(page);
  await page.goto("/");

  // No click, so no new tab: Settings, with the Open Google Calendar button.
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 70 events sent to Google.");
  await expect(page.getByRole("link", { name: "Open Google Calendar" })).toBeVisible();
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
  expect(page.context().pages()).toHaveLength(1);
  expect(api.googleVisits).toEqual([]);
});

test("a page 1 answered on an earlier visit starts on page 2", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.settings = { ...api.settings, address: HOME_PLACE, place_name: HOME_PLACE, time_zone: "America/Toronto", main_masjid_choice: "home" };
  await api.install(page);
  await page.goto("/");

  await expectPage(page, 2);
  await page.getByRole("button", { name: "← Back" }).click();
  await expectPage(page, 1);
  await expect(page.locator(".picked-masjid")).toContainText("I pray at home");
});

test("setup looks like the landing page: pages on the left on a computer, one line on a phone", async ({ page }, info) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  const steps = page.getByRole("complementary", { name: "Setup steps" });
  const question = page.getByRole("heading", { level: 1, name: "Required" });
  await expect(question).toBeVisible();
  if (info.project.name === "phone") {
    await expect(steps).toBeHidden();
    await expect(page.getByText("Setup · Step 1 of 2")).toBeVisible();
  } else {
    await expect(steps.getByRole("heading", { name: "Setup" })).toBeVisible();
    await expect(steps.getByRole("listitem")).toHaveText([/Required/, /Optional/]);
    await expect(steps.locator('[aria-current="step"]')).toHaveText(/Required/);
    await expect(page.getByText("Setup · Step 1 of 2")).toBeHidden();
    const left = await steps.boundingBox();
    const right = await question.boundingBox();
    expect(right!.x).toBeGreaterThan(left!.x + left!.width - 1);
  }
});

test("suggestions never show postal codes", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");

  await addressBox(page).pressSequentially("200 Kanata", { delay: 30 });

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
  await expect(page.getByRole("heading", { level: 1, name: "Required" })).toBeVisible();
  await page.evaluate(() => document.fonts.ready);

  const family = await page.getByRole("heading", { level: 1 }).evaluate((h) => getComputedStyle(h).fontFamily);
  expect(family).toContain("Plus Jakarta Sans");
  expect(await page.evaluate(() => document.fonts.check('16px "Plus Jakarta Sans Variable"'))).toBe(true);
  expect(fontRequests.length).toBeGreaterThan(0);
  expect(fontRequests.every((url) => url.startsWith("http://localhost:4173/assets/"))).toBe(true);
});

test("Skip saves the defaults", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);

  // Something typed and picked, then skipped: the defaults win.
  await page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?").fill("20");
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
  await page.getByRole("button", { name: "Skip" }).click();

  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toEqual({
    arrive_early_minutes: 5, jumuah_arrive_early_minutes: 5, prayer_color_id: "10", drive_color_id: "10",
  });
  await expectGoogleCalendar(page, api);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(1);
  expect([api.settings.prayer_color_id, api.settings.drive_color_id]).toEqual(["10", "10"]);
});

test("the colour dropdown works with the keyboard", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await toOptionalAtHome(page);

  const button = page.getByRole("button", { name: /^Drive colour/ });
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

test("how early takes whole numbers from 0 to 60 only, for prayers and for Jumuah", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);

  for (const label of ["How early do you want to arrive before iqamah (daily prayers)?", "How early do you want to arrive before Jumuah (Friday prayer)?"]) {
    const box = page.getByLabel(label);
    for (const bad of ["61", "-1", "2.5", "", "100"]) {
      await box.fill(bad);
      await page.getByRole("button", { name: "Finish" }).click();
      await expect(page.getByRole("alert")).toHaveText("Enter a whole number of minutes from 0 to 60.");
      await expect(box).toHaveAttribute("aria-invalid", "true");
    }
    await box.fill("60");
  }
  expect(api.calls("PUT", "/api/settings/optional")).toHaveLength(0);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
  expect(page.context().pages()).toHaveLength(1);

  // 60 is the most allowed. (0 is in the next test.)
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toMatchObject({
    arrive_early_minutes: 60, jumuah_arrive_early_minutes: 60,
  });
  await expectGoogleCalendar(page, api);
});

test("0 minutes early is allowed", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);

  await page.getByLabel("How early do you want to arrive before iqamah (daily prayers)?").fill("0");
  await page.getByLabel("How early do you want to arrive before Jumuah (Friday prayer)?").fill("0");
  await page.getByRole("button", { name: "Finish" }).click();
  expect((await api.sent("PUT", "/api/settings/optional", 1))[0].body).toMatchObject({
    arrive_early_minutes: 0, jumuah_arrive_early_minutes: 0,
  });
  await expectGoogleCalendar(page, api);
});

test("page 2: Optional heading, Drive colour, and Skip in the top-right corner", async ({ page }) => {
  await new MockApi().signedIn().install(page);
  await page.goto("/");
  await toOptionalAtKma(page);

  const heading = page.getByRole("heading", { level: 1, name: "Optional" });
  // The removed lines stay gone.
  for (const gone of ["All optional", "The drive block before each masjid prayer", "Google Calendar's own colours", "(optional)"]) {
    await expect(page.getByText(gone)).toHaveCount(0);
  }
  await expect(page.getByLabel("Short name for Kanata Muslim Association", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Drive colour/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^Commute colour/ })).toHaveCount(0);

  // Skip is level with the heading, at the right edge of the page.
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

test("Finish opens a new tab that shows a message, then Google Calendar, while this tab goes to Settings", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.finishDelayMs = 1500;
  await api.install(page);
  await page.goto("/");
  await toOptionalAtHome(page);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Finish" }).click();

  // The new tab opened inside the click, before the calendar was filled.
  const tab = await popup;
  await expect(tab).toHaveURL(/localhost:4173\/adding$/);
  await expect(tab.getByRole("heading", { level: 1, name: "Adding your prayers to Google Calendar..." })).toBeVisible();
  // This tab is on Settings already, saying the same.
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Adding your prayers to Google Calendar...");
  expect(api.googleVisits).toEqual([]);

  // Once the update finishes, the new tab opens Google Calendar for their account.
  await expectGoogleCalendar(page, api);
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 70 events sent to Google.");
  await expect(page.getByText("blocked the new tab")).toHaveCount(0);
  // The new tab can't reach back to this one.
  expect(await tab.evaluate(() => window.opener)).toBeNull();
});

test("a blocked new tab leaves Settings with the Open Google Calendar button and a note", async ({ page }) => {
  // Like a popup blocker: window.open gives nothing back.
  await page.addInitScript(() => {
    window.open = () => null;
  });
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await toOptionalAtHome(page);
  await page.getByRole("button", { name: "Finish" }).click();

  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 70 events sent to Google.");
  await expect(page.getByText("Your browser blocked the new tab, so open Google Calendar from here.")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open Google Calendar" })).toHaveAttribute("href", GOOGLE_CALENDAR);
  expect(api.googleVisits).toEqual([]);
});

test("if the first calendar update fails, both tabs show why", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.finishCalendar = {
    status: "waiting", sent: 40, waiting: 30,
    message: "Saved. Some prayers haven't reached Google Calendar yet. Try again in a minute.",
  };
  await api.install(page);
  await page.goto("/");
  await toOptionalAtHome(page);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Skip" }).click();
  const tab = await popup;

  // The new tab: the error and a link back to Settings. No Google Calendar.
  await expect(tab.getByRole("alert")).toHaveText(
    "Saved. Some prayers haven't reached Google Calendar yet. Try again in a minute.",
  );
  await expect(tab.getByRole("link", { name: "Back to Settings" })).toHaveAttribute("href", "/");
  // This tab: Settings with the same message and Try again.
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Some prayers haven't reached Google Calendar yet.");
  await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(api.googleVisits).toEqual([]);

  // The link back goes to Settings, in the new tab.
  await tab.getByRole("link", { name: "Back to Settings" }).click();
  await expect(tab.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});

test("if finishing setup fails, the new tab and Settings show the error, and Try again finishes it", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/setup/finish"] = { status: 503, detail: { message: "Google Calendar didn't answer. Try again in a minute." } };
  await api.install(page);
  await page.goto("/");
  await toOptionalAtHome(page);
  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Skip" }).click();
  const tab = await popup;

  await expect(tab.getByRole("alert")).toHaveText("Google Calendar didn't answer. Try again in a minute.");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.getByRole("status")).toContainText("Google Calendar didn't answer. Try again in a minute.");
  expect(api.googleVisits).toEqual([]);

  // Try again finishes setup. There's no click-opened tab this time, so nothing opens.
  await page.getByRole("button", { name: "Try again" }).click();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 70 events sent to Google.");
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(2);
  expect(api.googleVisits).toEqual([]);
});

test("the adding page opened by hand just links to Settings", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/adding");
  await expect(page.getByRole("heading", { level: 1, name: "Nothing to add here" })).toBeVisible();
  await expect(page.getByRole("link", { name: "Go to Settings" })).toHaveAttribute("href", "/");
  expect(api.requests).toEqual([]);
});

test("a failed save closes the new tab and stays on page 2", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/settings/optional"] = { status: 503, detail: { message: "The server is busy. Try again." } };
  await api.install(page);
  await page.goto("/");
  await toOptionalAtKma(page);
  await page.getByRole("button", { name: "Finish" }).click();

  await expect(page.getByRole("alert")).toHaveText("The server is busy. Try again.");
  await expect.poll(() => page.context().pages().length).toBe(1);
  await expectPage(page, 2);
  expect(api.calls("POST", "/api/setup/finish")).toHaveLength(0);
});

test("a failed Jumuah pick save stays on page 1 with the error", async ({ page }) => {
  const api = new MockApi().signedIn();
  api.failNext["/api/settings/jumuah-pick"] = { status: 503, detail: { message: "The server is busy. Try again." } };
  await api.install(page);
  await page.goto("/");
  await pickHome(page);
  await pickMasjid(page, "Kanata", "Kanata Muslim Association");
  await expect(page.getByRole("radio", { name: /1st Jumuah/ })).toBeChecked();
  await page.getByRole("button", { name: "Next" }).click();

  await expect(page.getByRole("alert")).toHaveText("The server is busy. Try again.");
  await expectPage(page, 1);
});
