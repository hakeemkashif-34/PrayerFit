// The "Adding your prayers to Google Calendar..." tab that Finish opens.
// It's opened with window.opener set, so here a test pretends the setup tab opened it.

import { expect, test, type Page } from "@playwright/test";
import { MockApi } from "./mock-api";

async function openAdding(page: Page, path = "/adding?colour=7") {
  await new MockApi().signedIn().install(page);
  // Like being opened by the setup tab, so the page waits instead of saying "Nothing to add here".
  await page.addInitScript(() => Object.defineProperty(window, "opener", { value: window, writable: true }));
  await page.goto(path);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Adding your prayers to Google Calendar...");
}

// True when the element's text sits on one line and isn't cut off.
const oneLine = (page: Page, selector: string) =>
  page.locator(selector).evaluate((el) => {
    const lineHeight = parseFloat(getComputedStyle(el).lineHeight);
    return el.getBoundingClientRect().height < lineHeight * 1.5 && el.scrollWidth <= el.clientWidth + 1;
  });

test("the heading and the line under it", async ({ page }) => {
  await openAdding(page);
  await expect(page.locator("main p")).toHaveText(["This can take up to a minute."]);
});

for (const width of [320, 390, 412, 768, 1280]) {
  test(`every line stays on one line at ${width}px wide`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    await openAdding(page);
    expect(await oneLine(page, "main h1")).toBe(true);
    expect(await oneLine(page, "main p")).toBe(true);
    // Nothing wider than the screen.
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
    // On phones from 390px up, still bigger than the line under it.
    // (A 320px screen is too narrow for that and one line both.)
    if (width >= 390) {
      const [heading, line] = await Promise.all(
        ["main h1", "main p"].map((s) => page.locator(s).evaluate((el) => parseFloat(getComputedStyle(el).fontSize))),
      );
      expect(heading).toBeGreaterThan(line);
    }
  });
}

test("a week of prayer blocks drops in, in the user's prayer colour, on a loop", async ({ page }) => {
  await openAdding(page);
  const week = page.locator(".mini-week");
  await expect(week).toBeVisible();
  await expect(week.locator(".mini-day")).toHaveText(["M", "T", "W", "T", "F", "S", "S"]);
  await expect(week.locator(".mini-block")).toHaveCount(35);
  await expect(page.locator(".spinner")).toBeHidden();

  const block = await week.locator(".mini-block").first().evaluate((el) => {
    const s = getComputedStyle(el);
    return { colour: s.backgroundColor, name: s.animationName, loops: s.animationIterationCount };
  });
  // Peacock (#039be5), from ?colour=7.
  expect(block.colour).toBe("rgb(3, 155, 229)");
  expect(block).toMatchObject({ name: "mini-drop", loops: "infinite" });
  // One by one: each block's turn comes a little after the one before.
  const delays = await week.locator(".mini-block").evaluateAll((blocks) =>
    blocks.map((b) => parseFloat(getComputedStyle(b).animationDelay)),
  );
  expect(new Set(delays).size).toBe(35);
  // Hidden from screen readers. The heading says what's happening.
  await expect(page.locator(".mini-week").locator("xpath=..")).toHaveAttribute("aria-hidden", "true");
});

test("a colour that isn't one of Google's uses the app's green", async ({ page }) => {
  await openAdding(page, "/adding?colour=red");
  const [block, green] = await Promise.all([
    page.locator(".mini-block").first().evaluate((el) => getComputedStyle(el).backgroundColor),
    page.locator("main").evaluate(() => {
      const probe = document.createElement("span");
      probe.style.color = "var(--green)";
      document.body.append(probe);
      return getComputedStyle(probe).color;
    }),
  ]);
  expect(block).toBe(green);
});

test("with motion turned off, a spinner shows instead", async ({ page }) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openAdding(page);
  await expect(page.locator(".mini-week")).toBeHidden();
  await expect(page.locator(".spinner")).toBeVisible();
});

test("the prayer colour picked in setup reaches the new tab", async ({ page }) => {
  const api = new MockApi().signedIn();
  await api.install(page);
  await page.goto("/");
  await page.getByRole("combobox", { name: "Address" }).pressSequentially("200 Kanata", { delay: 20 });
  await page.getByRole("option", { name: /^200 Kanata Avenue, Ottawa/ }).click();
  // The location is saved once the masjid search opens up.
  await expect(page.getByRole("combobox", { name: "Masjid" })).toBeEnabled();
  await page.getByRole("button", { name: "I pray at home" }).click();
  await page.getByRole("button", { name: "Next" }).click();
  await page.getByRole("button", { name: /^Prayer colour/ }).click();
  await page.getByRole("option", { name: "Grape" }).click();

  const popup = page.waitForEvent("popup");
  await page.getByRole("button", { name: "Finish" }).click();
  const tab = await popup;
  await expect(tab).toHaveURL(/\/adding\?colour=3$/);
  // Then on to Google Calendar, as before.
  await expect(tab).toHaveURL(/calendar\.google\.com/);
});
