// The private /stats page. Only the ADMIN_EMAIL account sees it. Everyone
// else gets "Page not found", and nothing links to it.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

async function openStats(page: Page, api = new MockApi().signedIn(finishedSettings())) {
  api.adminEmail = "hakeem@example.com";
  await api.install(page);
  await page.goto("/stats");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Stats");
  return api;
}

const tip = (page: Page) => page.locator(".graph-tip");
const boxes = (page: Page, selector: string) =>
  page.locator(selector).evaluateAll((els) => els.map((el) => el.getBoundingClientRect().toJSON() as DOMRect));
const overlap = (a: DOMRect, b: DOMRect) =>
  a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

test("only 3 things: total users, the graph, and the masjids", async ({ page }) => {
  await openStats(page);
  await expect(page.locator(".total-users")).toHaveText("Total users: 42");
  await expect(page.getByRole("heading", { level: 2 })).toHaveText(["Total users over time", "Masjids"]);
  // Everything else is gone.
  await expect(page.getByText(/Finished setup|Active|New this week|Linked automatically|no MAWAQIT match|Masjid times/)).toHaveCount(0);
  // Counts only: no emails anywhere on the page.
  await expect(page.getByText(/@/)).toHaveCount(0);
});

test("the graph has one dot per day, and hovering a dot shows that day", async ({ page }) => {
  await openStats(page);
  const dots = page.locator(".graph-box .dot");
  await expect(dots).toHaveCount(6);
  await dots.nth(1).hover();
  await expect(tip(page)).toHaveText(["Oct 213 signed up that day33 in total"]);
  await dots.last().hover();
  await expect(tip(page)).toHaveText(["Oct 252 signed up that day42 in total"]);
  // The box never runs off the graph, even at the last dot, and never covers the dot it's about.
  const [box, graph, dot] = await Promise.all([
    tip(page).boundingBox(), page.locator(".graph-box").boundingBox(), dots.last().boundingBox(),
  ]);
  expect(box!.x + box!.width).toBeLessThanOrEqual(graph!.x + graph!.width + 1);
  const covers = box!.x < dot!.x + dot!.width && dot!.x < box!.x + box!.width && box!.y < dot!.y + dot!.height && dot!.y < box!.y + box!.height;
  expect(covers).toBe(false);
});

test("moving the mouse off the dot hides the box, and the rest of the graph shows nothing", async ({ page }) => {
  await openStats(page);
  const dots = page.locator(".graph-box .dot");
  await dots.nth(2).hover();
  await expect(tip(page)).toContainText("Oct 22");
  // A spot in the graph away from every dot: the middle of the empty area under the line.
  const graph = (await page.locator(".graph-box svg").boundingBox())!;
  await page.mouse.move(graph.x + graph.width * 0.5, graph.y + graph.height * 0.85);
  await expect(tip(page)).toHaveCount(0);
  // Moving around the empty area never shows it either.
  await page.mouse.move(graph.x + graph.width * 0.3, graph.y + graph.height * 0.8);
  await expect(tip(page)).toHaveCount(0);
});

test("tapping a dot shows the box, and tapping anywhere else hides it", async ({ page }) => {
  await openStats(page);
  const first = page.locator(".graph-box .dot").first();
  await first.dispatchEvent("pointerdown", { pointerType: "touch" });
  // Lifting the finger fires "leave", which must not hide it.
  await first.dispatchEvent("pointerleave", { pointerType: "touch" });
  await expect(tip(page)).toContainText("Oct 20");
  await expect(tip(page)).toContainText("30 signed up that day");
  await expect(tip(page)).toContainText("30 in total");
  // A tap on another dot moves the box there.
  await page.locator(".graph-box .dot").nth(3).dispatchEvent("pointerdown", { pointerType: "touch" });
  await expect(tip(page)).toContainText("Oct 23");
  // A tap anywhere else hides it.
  await page.getByRole("heading", { level: 1 }).dispatchEvent("pointerdown", { pointerType: "touch" });
  await expect(tip(page)).toHaveCount(0);
});

test("the dots work with the keyboard", async ({ page }) => {
  await openStats(page);
  await page.locator(".graph-box .dot").nth(2).focus();
  await expect(tip(page)).toContainText("Oct 22");
  // Tab moves to the next day, and leaving the graph hides it.
  await page.keyboard.press("Tab");
  await expect(tip(page)).toContainText("Oct 23");
  await page.locator(".graph-box .dot").nth(3).blur();
  await expect(tip(page)).toHaveCount(0);
  await expect(page.locator(".graph-box .dot").nth(2)).toHaveAttribute("aria-label", "Oct 22: 2 signed up, 35 in total");
});

test("no labels overlap at the start of the graph, and the text stays readable", async ({ page }) => {
  await openStats(page);
  const ticks = await boxes(page, ".graph-box .tick");
  for (let i = 0; i < ticks.length; i++) {
    for (let j = i + 1; j < ticks.length; j++) expect(overlap(ticks[i], ticks[j])).toBe(false);
  }
  // The graph is drawn at its real width, so 12px text is 12px on a phone too.
  const size = await page.locator(".graph-box .tick").first().evaluate((el) => el.getBoundingClientRect().height);
  expect(size).toBeGreaterThan(10);
});

test("the masjids, most users first, with a tag on those with no MAWAQIT times", async ({ page }) => {
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

test("with nobody yet, the graph and the table say so", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.stats = { total_users: 0, history: [], masjids: [] };
  await openStats(page, api);
  await expect(page.locator(".total-users")).toHaveText("Total users: 0");
  await expect(page.getByText("Nobody has signed up yet.")).toBeVisible();
  await expect(page.getByText("Nobody has picked a masjid yet.")).toBeVisible();
});

test("nothing is wider than the screen", async ({ page }) => {
  await openStats(page);
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
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
