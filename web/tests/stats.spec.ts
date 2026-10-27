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

// The plot's left and right padding in StatsPage.tsx: dates on the left edge, value labels on the right.
const PAD_LEFT = 22;
const PAD_RIGHT = 48;

// Puts the mouse over point i of `count`, the way a person would point at it.
async function hover(page: Page, i: number, count: number) {
  const svg = (await page.locator(".graph-box svg").boundingBox())!;
  const width = svg.width - PAD_LEFT - PAD_RIGHT;
  await page.mouse.move(svg.x + PAD_LEFT + (i / (count - 1)) * width, svg.y + svg.height * 0.6);
}

// A graph of `days` days, ending Oct 26, with these totals.
function daily(totals: number[]): import("../src/types").UsersGraph {
  return {
    step: "day",
    points: totals.map((total, i) => ({ start: new Date(Date.UTC(2026, 9, 27 - totals.length + i, 4)).toISOString(), total })),
  };
}

// The value labels on the right, top to bottom read as numbers from 0 up.
const valueLabels = (page: Page) => page.locator(".graph-box .tick.value").allTextContents();

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
});

test("one big sentence above the graph says today's total", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.usersGraphs["30d"] = daily([...Array(29).fill(900), 1234]);
  await openStats(page, api);
  const total = page.locator(".users-total");
  await expect(total).toHaveText("PrayerFit has 42 users");
  // It sits above the graph and is the biggest text in the card.
  const [sentence, graph] = await Promise.all([total.boundingBox(), page.locator(".graph-box").boundingBox()]);
  expect(sentence!.y + sentence!.height).toBeLessThanOrEqual(graph!.y);
  expect(parseFloat(await total.evaluate((el) => getComputedStyle(el).fontSize))).toBeGreaterThan(
    parseFloat(await page.locator("#graph-title").evaluate((el) => getComputedStyle(el).fontSize)),
  );
  await range(page).selectOption("30d");
  await expect(total).toHaveText("PrayerFit has 1,234 users");
});

test("one user says user, not users", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.usersGraphs["7d"] = daily([0, 0, 0, 0, 0, 1, 1]);
  await openStats(page, api);
  await expect(page.locator(".users-total")).toHaveText("PrayerFit has 1 user");
});

test("one thin line of straight segments, and no dot on any point until you point at one", async ({ page }) => {
  await openStats(page);
  const line = page.locator(".graph-box .series");
  await expect(line).toHaveCount(1);
  // Only "move to" and "line to": no curves, which could draw a dip that never happened.
  const d = (await line.getAttribute("d"))!;
  expect(d).toMatch(/^M[\d.,]+( L[\d.,]+)+$/);
  expect(d.match(/L/g)).toHaveLength(6);
  expect(parseFloat(await line.evaluate((el) => getComputedStyle(el).strokeWidth))).toBeLessThanOrEqual(2);
  await expect(page.locator(".graph-box circle")).toHaveCount(0);
  await hover(page, 3, 7);
  await expect(page.locator(".graph-box circle")).toHaveCount(1);
});

test("the value labels are on the right: 4 or 5 whole numbers from 0, just above the highest total", async ({ page }) => {
  await openStats(page);
  // The highest total is 42.
  expect(await valueLabels(page)).toEqual(["0", "20", "40", "60"]);
  // Each one sits on its own grid line, to the right of the plot.
  const [label, plot] = await Promise.all([
    page.locator(".graph-box .tick.value").first().boundingBox(), page.locator(".graph-box .series").boundingBox(),
  ]);
  expect(label!.x).toBeGreaterThan(plot!.x + plot!.width);
  await expect(page.locator(".graph-box .grid")).toHaveCount(4);
});

for (const [highest, labels] of [
  [0, ["0", "1", "2", "3"]],
  [1, ["0", "1", "2", "3"]],
  [3, ["0", "1", "2", "3", "4"]],
  [7, ["0", "2", "4", "6", "8"]],
  [12, ["0", "5", "10", "15"]],
  [99, ["0", "25", "50", "75", "100"]],
  [999, ["0", "250", "500", "750", "1K"]],
  [1148, ["0", "500", "1K", "1.5K"]],
  [12000, ["0", "5K", "10K", "15K"]],
] as const) {
  test(`with a highest total of ${highest}, the value labels are ${labels.join(", ")}`, async ({ page }) => {
    const api = new MockApi().signedIn(finishedSettings());
    api.usersGraphs["7d"] = daily([0, 0, 0, 0, 0, 0, highest]);
    await openStats(page, api);
    expect(await valueLabels(page)).toEqual([...labels]);
  });
}

// Lots of points for every range, so each picks its own labels.
function wideGraphs(api: MockApi) {
  const hours = (count: number) => ({
    step: "hour" as const,
    points: Array.from({ length: count }, (_, i) => ({
      start: new Date(Date.UTC(2026, 9, 26, 16 - count + 1 + i)).toISOString(), total: 40,
    })),
  });
  api.usersGraphs["2d"] = hours(48);
  api.usersGraphs["3d"] = hours(72);
  api.usersGraphs["5d"] = daily([1, 2, 3, 4, 5]);
  api.usersGraphs["30d"] = daily(Array.from({ length: 30 }, (_, i) => i));
  api.usersGraphs["all"] = daily(Array.from({ length: 200 }, (_, i) => i));
}

for (const choice of ["1d", "2d", "3d", "5d", "7d", "30d", "all"] as const) {
  test(`${choice}: 5 to 7 bottom labels, evenly spaced, never touching`, async ({ page }) => {
    const api = new MockApi().signedIn(finishedSettings());
    wideGraphs(api);
    await openStats(page, api);
    await range(page).selectOption(choice);
    await expect.poll(() => api.rangesAsked.at(-1)).toBe(choice);
    const labels = page.locator(".graph-box .tick.date");
    await expect(labels.first()).toBeVisible();
    const found = await boxes(page, ".graph-box .tick.date");
    expect(found.length).toBeGreaterThanOrEqual(5);
    expect(found.length).toBeLessThanOrEqual(7);
    // The same gap between every pair of centres, to within a pixel.
    const centres = found.map((b) => b.left + b.width / 2);
    const gaps = centres.slice(1).map((c, i) => c - centres[i]);
    for (const gap of gaps) expect(Math.abs(gap - gaps[0])).toBeLessThan(1.5);
    const ticks = await boxes(page, ".graph-box .tick");
    for (let i = 0; i < ticks.length; i++) {
      for (let j = i + 1; j < ticks.length; j++) expect(overlap(ticks[i], ticks[j])).toBe(false);
    }
    // Hours for 1 to 3 days, dates after that. Midnight shows the date, so the days are clear.
    const texts = await labels.allTextContents();
    if (["1d", "2d", "3d"].includes(choice)) {
      for (const t of texts) expect(t).toMatch(/^(\d{1,2} (AM|PM)|[A-Z][a-z]{2} \d{1,2})$/);
      expect(texts.some((t) => /M$/.test(t))).toBe(true);
    } else {
      for (const t of texts) expect(t).toMatch(/^[A-Z][a-z]{2} \d{1,2}$/);
    }
  });
}

test("1 day: hours along the bottom, in Toronto time", async ({ page }) => {
  const api = await openStats(page);
  await range(page).selectOption("1d");
  expect(api.rangesAsked).toEqual(["7d", "1d"]);
  // 20:00 UTC is 4 PM in Toronto (EDT). Every 4 hours, and midnight is the date.
  await expect(page.locator(".graph-box .tick.date")).toHaveText(["4 PM", "8 PM", "Oct 26", "4 AM", "8 AM", "12 PM"]);
});

test("hovering shows a dot on the line and a card above it with the date and the total", async ({ page }) => {
  await openStats(page);
  await hover(page, 1, 7);
  await expect(tip(page)).toHaveText(["Oct 2133 users"]);
  // Someone deleted their account on Oct 24, so the total went down.
  await hover(page, 4, 7);
  await expect(tip(page)).toHaveText(["Oct 2437 users"]);
  await expect(tip(page).locator("strong")).toHaveText("37");
  // The total is large and bold.
  const weight = await tip(page).locator("strong").evaluate((el) => Number(getComputedStyle(el).fontWeight));
  expect(weight).toBeGreaterThanOrEqual(700);
  // The card is above its dot.
  const [card, dot] = await Promise.all([tip(page).boundingBox(), page.locator(".graph-box .dot.picked").boundingBox()]);
  expect(card!.y + card!.height).toBeLessThan(dot!.y);
  await hover(page, 6, 7);
  await expect(tip(page)).toHaveText(["Oct 2642 users"]);
});

test("hovering an hour shows the hour too", async ({ page }) => {
  await openStats(page);
  await range(page).selectOption("1d");
  await expect(page.locator(".graph-box .tick.date").first()).toHaveText("4 PM");
  await hover(page, 0, 24);
  await expect(tip(page)).toHaveText(["Oct 25, 1:00 PM40 users"]);
  await hover(page, 23, 24);
  await expect(tip(page)).toHaveText(["Oct 26, 12:00 PM41 users"]);
});

test("moving the mouse off the graph hides the card", async ({ page }) => {
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
  await hit.dispatchEvent("pointerdown", { pointerType: "touch", clientX: svg.x + PAD_LEFT, clientY: hitBox.y + 100 });
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
  await expect(page.locator(".graph-box .dot.picked")).toHaveCount(1);
  await page.keyboard.press("ArrowLeft");
  await expect(tip(page)).toContainText("Oct 25");
  await page.keyboard.press("Home");
  await expect(tip(page)).toContainText("Oct 20");
  await page.keyboard.press("End");
  await expect(tip(page)).toContainText("Oct 26");
  await page.locator(".graph-box svg").blur();
  await expect(tip(page)).toHaveCount(0);
});

test("the card never runs off the graph or covers its point", async ({ page }) => {
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

test("the graph's text stays readable on every screen", async ({ page }) => {
  await openStats(page);
  // The graph is drawn at its real width, so the labels keep their size on a phone too.
  for (const selector of [".graph-box .tick.value", ".graph-box .tick.date"]) {
    const size = await page.locator(selector).first().evaluate((el) => el.getBoundingClientRect().height);
    expect(size).toBeGreaterThan(10);
  }
});

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
  for (const choice of ["7d", "1d", "30d"]) {
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
