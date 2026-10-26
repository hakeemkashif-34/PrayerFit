// The private /stats page. Only the ADMIN_EMAIL account sees it. Everyone
// else gets "Page not found", and nothing links to it.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

async function openStats(page: Page, api = new MockApi().signedIn(finishedSettings())) {
  api.adminEmail = "hakeem@example.com";
  await api.install(page);
  await page.goto("/stats");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Stats");
  await expect(page.locator(".graph-box svg")).toBeVisible();
  return api;
}

const tip = (page: Page) => page.locator(".graph-tip");
const range = (page: Page) => page.getByLabel("Show");

// Puts the mouse over point i of `count`, the way a person would point at it.
async function hover(page: Page, i: number, count: number) {
  const svg = (await page.locator(".graph-box svg").boundingBox())!;
  const left = svg.x + 44; // PAD.left
  const width = svg.width - 44 - 24; // minus PAD.left and PAD.right
  await page.mouse.move(left + (i / (count - 1)) * width, svg.y + svg.height * 0.5);
}

const boxes = (page: Page, selector: string) =>
  page.locator(selector).evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON() as DOMRect));
const overlap = (a: DOMRect, b: DOMRect) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

test("2 cards: the graph and the masajid. No total users card", async ({ page }) => {
  await openStats(page);
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Total users over time", "Masajid"]);
  await expect(page.locator(".total-users")).toHaveCount(0);
  await expect(page.getByText(/Total users:/)).toHaveCount(0);
  // Counts only: no emails anywhere on the page.
  await expect(page.getByText(/@/)).toHaveCount(0);
});

test("the word Masjid only appears as the card's title, Masajid", async ({ page }) => {
  await openStats(page);
  const text = await page.locator("main").innerText();
  expect(text.match(/masajid/gi)).toEqual(["Masajid"]);
  expect(text.match(/masjids?\b/gi)).toBeNull();
  // The right column says just "Users". The names' column has no visible header.
  const headers = page.locator(".masjid-table thead th");
  await expect(headers.nth(1)).toHaveText("Users");
  await expect(headers.nth(0).locator(".visually-hidden")).toHaveText("Name");
});

test("the masajid, most users first, with a tag on those with no MAWAQIT times", async ({ page }) => {
  await openStats(page);
  const rows = page.locator(".masjid-table tbody tr");
  await expect(rows).toHaveText([
    "Kanata Muslim Association30",
    "Jamia OmarNo MAWAQIT times8",
    "(picked by address)No MAWAQIT times1",
  ]);
  await expect(rows.first().locator(".tag")).toHaveCount(0);
  await expect(page.locator(".masjid-table .tag")).toHaveCount(2);
});

test("the dropdown has every range and starts on 7 days", async ({ page }) => {
  const api = await openStats(page);
  await expect(range(page).locator("option")).toHaveText(["1 day", "2 days", "3 days", "5 days", "7 days", "30 days", "All time"]);
  await expect(range(page)).toHaveValue("7d");
  expect(api.rangesAsked).toEqual(["7d"]);
  await expect(page.getByText("Total users, one point per day.", { exact: false })).toBeVisible();
});

test("7 days: one dot per day, and hovering shows the date and the total", async ({ page }) => {
  await openStats(page);
  await expect(page.locator(".graph-box .dot")).toHaveCount(7);
  await hover(page, 1, 7);
  await expect(tip(page)).toHaveText(["Oct 2133 users"]);
  // Someone deleted their account on Oct 24, so the total went down.
  await hover(page, 4, 7);
  await expect(tip(page)).toHaveText(["Oct 2437 users"]);
  await hover(page, 6, 7);
  await expect(tip(page)).toHaveText(["Oct 2642 users"]);
});

test("1 day: one point per hour, in Toronto time", async ({ page }) => {
  const api = await openStats(page);
  await range(page).selectOption("1d");
  await expect(page.getByText("Total users, one point per hour.", { exact: false })).toBeVisible();
  expect(api.rangesAsked).toEqual(["7d", "1d"]);
  // 17:00 UTC is 1:00 PM in Toronto (EDT).
  await expect(page.locator(".graph-box .tick.date")).toHaveText(["Oct 25, 1:00 PM", "Oct 26, 12:00 PM"]);
  await hover(page, 0, 24);
  await expect(tip(page)).toHaveText(["Oct 25, 1:00 PM40 users"]);
  await hover(page, 23, 24);
  await expect(tip(page)).toHaveText(["Oct 26, 12:00 PM41 users"]);
});

test("3 days and up have too many points for dots, so only the line and the picked one show", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.usersGraphs["3d"] = {
    step: "hour",
    points: Array.from({ length: 72 }, (_, i) => ({ start: new Date(Date.UTC(2026, 9, 23, 17 + i)).toISOString(), total: 1 })),
  };
  await openStats(page, api);
  await range(page).selectOption("3d");
  await expect(page.locator(".graph-box .tick.date").first()).toHaveText("Oct 23, 1:00 PM");
  await expect(page.locator(".graph-box .dot")).toHaveCount(0);
  await hover(page, 36, 72);
  await expect(page.locator(".graph-box .dot")).toHaveCount(1);
  await expect(tip(page)).toHaveText(["Oct 25, 1:00 AM1 user"]);
});

test("moving the mouse off the graph hides the box", async ({ page }) => {
  await openStats(page);
  await hover(page, 2, 7);
  await expect(tip(page)).toContainText("Oct 22");
  await page.mouse.move(5, 5);
  await expect(tip(page)).toHaveCount(0);
});

test("tapping the graph shows the closest point, and tapping anywhere else hides it", async ({ page }) => {
  await openStats(page);
  const hit = page.locator(".plot-hit");
  const svg = (await page.locator(".graph-box svg").boundingBox())!;
  const hitBox = (await hit.boundingBox())!;
  // A tap at the very left of the plot is the first day.
  await hit.dispatchEvent("pointerdown", { pointerType: "touch", clientX: svg.x + 44, clientY: hitBox.y + 20 });
  // Lifting the finger fires "leave", which must not hide it.
  await hit.dispatchEvent("pointerleave", { pointerType: "touch" });
  await expect(tip(page)).toHaveText(["Oct 2030 users"]);
  await page.getByRole("heading", { level: 1 }).dispatchEvent("pointerdown", { pointerType: "touch" });
  await expect(tip(page)).toHaveCount(0);
});

test("the graph works with the keyboard", async ({ page }) => {
  await openStats(page);
  await page.locator(".graph-box svg").focus();
  // It starts on the newest point.
  await expect(tip(page)).toContainText("Oct 26");
  await page.keyboard.press("ArrowLeft");
  await expect(tip(page)).toContainText("Oct 25");
  await page.keyboard.press("Home");
  await expect(tip(page)).toContainText("Oct 20");
  await page.keyboard.press("End");
  await expect(tip(page)).toContainText("Oct 26");
  await page.locator(".graph-box svg").blur();
  await expect(tip(page)).toHaveCount(0);
});

test("the box never runs off the graph or covers its point", async ({ page }) => {
  await openStats(page);
  for (const i of [0, 3, 6]) {
    await hover(page, i, 7);
    const [box, graph, dot] = await Promise.all([
      tip(page).boundingBox(), page.locator(".graph-box").boundingBox(), page.locator(".graph-box .dot.picked").boundingBox(),
    ]);
    expect(box!.x).toBeGreaterThanOrEqual(graph!.x - 1);
    expect(box!.x + box!.width).toBeLessThanOrEqual(graph!.x + graph!.width + 1);
    const covers = box!.x < dot!.x + dot!.width && dot!.x < box!.x + box!.width && box!.y < dot!.y + dot!.height && dot!.y < box!.y + box!.height;
    expect(covers).toBe(false);
  }
});

for (const choice of ["7d", "1d"] as const) {
  test(`no labels overlap, and the text stays readable (${choice})`, async ({ page }) => {
    await openStats(page);
    await range(page).selectOption(choice);
    await expect(page.locator(".graph-box .tick.date").first()).toBeVisible();
    const ticks = await boxes(page, ".graph-box .tick");
    for (let i = 0; i < ticks.length; i++) {
      for (let j = i + 1; j < ticks.length; j++) expect(overlap(ticks[i], ticks[j])).toBe(false);
    }
    // The graph is drawn at its real width, so 12px text is 12px on a phone too.
    const size = await page.locator(".graph-box .tick").first().evaluate((el) => el.getBoundingClientRect().height);
    expect(size).toBeGreaterThan(10);
  });
}

test("with nobody yet, the graph and the table say so", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.stats = { masjids: [] };
  api.usersGraphs["7d"] = { step: "day", points: [] };
  api.adminEmail = "hakeem@example.com";
  await api.install(page);
  await page.goto("/stats");
  await expect(page.getByText("Nobody has signed up yet.")).toBeVisible();
  await expect(page.getByText("Nobody has picked one yet.")).toBeVisible();
});

test("nothing is wider than the screen", async ({ page }) => {
  await openStats(page);
  for (const choice of ["7d", "1d"]) {
    await range(page).selectOption(choice);
    const width = await page.evaluate(() => document.documentElement.clientWidth);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
  }
});

for (const who of ["someone else", "nobody signed in"] as const) {
  test(`${who} gets "Page not found"`, async ({ page }) => {
    const api = new MockApi();
    if (who === "someone else") api.signedIn(finishedSettings());
    api.adminEmail = "admin@example.com";
    await api.install(page);
    await page.goto("/stats");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
    await expect(page.getByText("Total users")).toHaveCount(0);
  });
}

test("nothing links to /stats", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.adminEmail = "hakeem@example.com";
  await api.install(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  await expect(page.locator('a[href*="stats"]')).toHaveCount(0);
});
