import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

const HADITH = "The Prophet ﷺ was asked which deed is most beloved to Allah, and he said praying on time.";

test("signed-out users see the welcome, the hadith, and a Sign in with Google card", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/");

  // Top to bottom: the heading, the line under it, then the hadith with its source on its own line.
  const welcome = page.locator(".welcome");
  await expect(page).toHaveTitle("PrayerFit");
  await expect(welcome.getByRole("heading", { level: 1 })).toHaveText("Welcome to PrayerFit");
  await expect(welcome.locator("p.lead")).toHaveText(
    "An app that syncs your daily prayers and masjid times to your Google Calendar, based on your location and planned around your day.",
  );
  await expect(welcome.locator("blockquote")).toHaveText(HADITH);
  await expect(welcome.locator("figcaption")).toHaveText("Sahih al-Bukhari 527");
  const [heading, lead, quote, source] = await Promise.all(
    ["h1", "p.lead", "blockquote", "figcaption"].map((s) => welcome.locator(s).boundingBox()),
  );
  expect(heading!.y).toBeLessThan(lead!.y);
  expect(lead!.y).toBeLessThan(quote!.y);
  expect(source!.y).toBeGreaterThanOrEqual(quote!.y + quote!.height - 1);

  const button = page.getByRole("link", { name: "Sign in with Google" });
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("href", "/auth/google/login");
  // The line about only having access to the Prayers calendar is gone.
  await expect(page.getByText("Never Gmail")).toHaveCount(0);
  await expect(page.getByText(/only asks for access/)).toHaveCount(0);
  // No OpenStreetMap data on this page, so no credit footer.
  await expect(page.getByRole("contentinfo")).toHaveCount(0);
});

for (const scheme of ["light", "dark"] as const) {
  test(`the hadith stands out in its own serif style (${scheme} mode)`, async ({ page }) => {
    await page.emulateMedia({ colorScheme: scheme });
    await new MockApi().install(page);
    await page.goto("/");
    const quote = page.locator(".hadith blockquote p");
    await expect(quote).toBeVisible();
    await page.evaluate(() => document.fonts.ready);

    const style = (selector: string) =>
      page.locator(selector).first().evaluate((el) => {
        const s = getComputedStyle(el);
        return { family: s.fontFamily, size: parseFloat(s.fontSize), colour: s.color, background: s.backgroundColor, border: s.borderLeftWidth };
      });
    const [hadith, block, heading, body] = await Promise.all([
      style(".hadith blockquote p"), style(".hadith"), style(".welcome h1"), style("body"),
    ]);
    // A serif (Amiri, which has the ﷺ sign), bigger than everything else on the page, including the heading.
    expect(hadith.family).toContain("Amiri");
    expect(await page.evaluate(() => document.fonts.check('16px "Amiri"', "ﷺ"))).toBe(true);
    expect(hadith.size).toBeGreaterThan(heading.size);
    // A white quote block with a green bar, set apart from the light green page. Near-black text, like the heading.
    expect(block.background).toBe("rgb(255, 255, 255)");
    expect(body.background).not.toBe(block.background);
    expect(parseFloat(block.border)).toBeGreaterThanOrEqual(4);
    expect(hadith.colour).toBe(heading.colour);
  });
}

test('"praying on time" stands out: bold, on a soft gold highlight around the whole words', async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/");
  await page.evaluate(() => document.fonts.ready);
  const words = page.locator(".hadith .on-time");
  await expect(words).toHaveText("praying on time");
  const look = await words.evaluate((el) => {
    const s = getComputedStyle(el);
    return {
      weight: Number(s.fontWeight), background: s.backgroundColor, colour: s.color, radius: parseFloat(s.borderTopLeftRadius),
      size: parseFloat(s.fontSize), top: parseFloat(s.paddingTop), bottom: parseFloat(s.paddingBottom),
      left: parseFloat(s.paddingLeft), right: parseFloat(s.paddingRight), lines: el.getClientRects().length,
    };
  });
  expect(look.weight).toBeGreaterThanOrEqual(700);
  // A solid soft gold (#fbe08a), a little brighter than the old #f6e2a6, with slightly rounded corners.
  expect(look.background).toBe("rgb(251, 224, 138)");
  expect(look.radius).toBeGreaterThan(0);
  // A little padding on every side, and about the same above and below the words.
  for (const side of [look.top, look.bottom, look.left, look.right]) expect(side).toBeGreaterThan(0);
  expect(Math.abs(look.top - look.bottom)).toBeLessThan(look.size * 0.05);
  // Just the height of the words, not Amiri's tall line box (about 1.75 times the font size).
  const box = (await words.boundingBox())!;
  expect(box.height).toBeLessThan(look.size * 1.3);
  // On 1 line and inside the screen, even on a phone, so the phrase is never split.
  expect(look.lines).toBe(1);
  expect(box.x + box.width).toBeLessThanOrEqual(page.viewportSize()!.width);
  // The same near-black as the rest of the hadith, so it's easy to read on the gold.
  expect(look.colour).toBe(await page.locator(".hadith blockquote p").evaluate((el) => getComputedStyle(el).color));
  // Only those words. The rest of the hadith has no highlight.
  expect(await page.locator(".hadith blockquote p").evaluate((el) => getComputedStyle(el).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
});

test("light only: the same white, black, and green on light green, even with dark mode turned on", async ({ page }) => {
  const colours = async () => {
    const body = await page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
    const button = await page.getByRole("link", { name: "Sign in with Google" }).evaluate((el) => {
      const s = getComputedStyle(el);
      return [s.backgroundColor, s.color];
    });
    const heading = await page.locator("h1").evaluate((el) => getComputedStyle(el).color);
    return { body, button, heading };
  };
  await new MockApi().install(page);
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/");
  const light = await colours();
  // Light green page, a green button with white text, near-black headings.
  expect(light).toEqual({
    body: "rgb(232, 243, 234)", button: ["rgb(23, 102, 63)", "rgb(255, 255, 255)"], heading: "rgb(11, 21, 16)",
  });
  await page.emulateMedia({ colorScheme: "dark" });
  expect(await colours()).toEqual(light);
});

test("text is bigger than the browser's 16px, and bigger again on a computer", async ({ page }, info) => {
  await new MockApi().install(page);
  await page.goto("/");
  const size = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  expect(size).toBe(info.project.name === "phone" ? 17 : 18);
  // Nothing wider than the screen.
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});

test("the welcome is on the left on a computer, and the sign-in card on the right", async ({ page }, info) => {
  await new MockApi().install(page);
  await page.goto("/");

  const welcome = await page.getByRole("heading", { name: "Welcome to PrayerFit" }).boundingBox();
  const card = await page.getByRole("region", { name: "Sign in" }).boundingBox();
  if (info.project.name === "phone") {
    expect(card!.y).toBeGreaterThan(welcome!.y + welcome!.height); // stacked
  } else {
    expect(card!.x).toBeGreaterThan(welcome!.x + welcome!.width - 1); // side by side
  }
});

test("a cancelled sign-in shows a fixed message", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/?sign_in_error=cancelled");

  await expect(page.getByRole("alert")).toHaveText("Google sign-in was cancelled. Try again when you're ready.");
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
});

test("an expired Google sign-in shows Sign in again, not an error", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings(), { google_sign_in_needed: true }).install(page);
  await page.goto("/");

  await expect(page.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
  await expect(page.getByText("Your settings are still saved")).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
});

test("Google expiring in the middle of an edit switches to Sign in again", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");
  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();

  api.failNext["/api/settings/weekly"] = {
    status: 401,
    detail: { message: "Google sign-in expired. Sign in again.", reason: "google_sign_in_expired", login_url: "/auth/google/login" },
  };
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("link", { name: "Sign in again" })).toBeVisible();
});
