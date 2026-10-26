import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

const HADITH = "The Prophet ﷺ was asked which deed is most beloved to Allah, and he said praying on time.";

test("signed-out users see the welcome, the hadith, and a Sign in with Google card", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/");

  // Top to bottom: the heading, the line under it, then the hadith with its source on its own line.
  const welcome = page.locator(".welcome");
  await expect(welcome.getByRole("heading", { level: 1 })).toHaveText("Welcome to Muslim Calendar");
  await expect(welcome.locator("p.lead")).toHaveText("Keep your prayer times up to date, every day.");
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
    // A quote block with its own background and an accent bar, set apart from the page.
    expect(block.background).not.toBe(body.background);
    expect(parseFloat(block.border)).toBeGreaterThanOrEqual(4);
    expect(hadith.colour).not.toBe(heading.colour);
  });
}

test("dark mode changes the page colours", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await new MockApi().install(page);
  await page.goto("/");
  const background = await page.locator("body").evaluate((el) => getComputedStyle(el).backgroundColor);
  // Dark: every channel is low.
  const [r, g, b] = background.match(/\d+/g)!.map(Number);
  expect(Math.max(r, g, b)).toBeLessThan(60);
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

  const welcome = await page.getByRole("heading", { name: "Welcome to Muslim Calendar" }).boundingBox();
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
