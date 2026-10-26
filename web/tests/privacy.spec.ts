// The privacy policy. Google checks that it's public and that the home
// page links to it, so both are tested here.

import { expect, test } from "@playwright/test";
import { MockApi } from "./mock-api";

test("the privacy page opens without signing in", async ({ page }) => {
  const api = new MockApi();
  await api.install(page);
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy policy");
  // The 2 calendar permissions, the Limited Use line, and a way to reach me.
  await expect(page.getByText("calendar.app.created")).toBeVisible();
  await expect(page.getByText("calendar.freebusy")).toBeVisible();
  await expect(page.getByRole("link", { name: "Google API Services User Data Policy" })).toBeVisible();
  await expect(page.getByRole("link", { name: "hakeemkashif34@gmail.com" })).toHaveAttribute("href", "mailto:hakeemkashif34@gmail.com");
  // It never asks who you are.
  expect(api.calls("GET", "/api/me")).toHaveLength(0);
});

test("the landing page links to the privacy page", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome to PrayerFit");
  await page.getByRole("link", { name: "Privacy" }).click();
  await expect(page).toHaveURL(/\/privacy$/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Privacy policy");
});

test("the privacy page is no wider than the screen", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/privacy");
  const width = await page.evaluate(() => document.documentElement.clientWidth);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
});
