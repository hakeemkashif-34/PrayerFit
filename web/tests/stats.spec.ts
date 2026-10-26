// The private /stats page. Only the ADMIN_EMAIL account sees it. Everyone
// else gets "Page not found", and nothing links to it.

import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

test("the admin sees the 4 counts, a graph, and masjid times that need a look", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  api.adminEmail = "hakeem@example.com";
  api.stats.masjid_times = [
    { name: "Kanata Muslim Association", source: "mawaqit", last_success_at: "2026-10-24T08:00:00Z", error: "status 403" },
  ];
  await api.install(page);
  await page.goto("/stats");

  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Stats");
  await expect(page.locator(".stat-tile")).toHaveText(["42Signed up", "30Finished setup", "25Active", "6New this week"]);
  await expect(page.getByRole("img", { name: /Sign-ups and active users over time/ })).toBeVisible();
  // Both lines are labelled, so colour isn't the only way to tell them apart.
  await expect(page.locator(".end-label")).toHaveText(["Signed up", "Active"]);
  // Every value is also in a table.
  await page.getByText("Show as a table").click();
  await expect(page.locator(".graph-table tbody tr")).toHaveCount(6);
  await expect(page.locator(".graph-table tbody tr").last()).toHaveText("Oct 254225");
  // Hovering shows that day's numbers.
  const graph = page.locator(".graph-box svg");
  const box = (await graph.boundingBox())!;
  await page.mouse.move(box.x + box.width * 0.06, box.y + box.height / 2);
  await expect(page.locator(".graph-tip")).toContainText("Oct 20");
  await expect(page.locator(".graph-tip")).toContainText("30 signed up");

  const masjids = page.getByRole("region", { name: "Masjid times" });
  await expect(masjids).toContainText("Kanata Muslim Association");
  await expect(masjids).toContainText("Error: status 403");
  // Counts only: no emails anywhere on the page.
  await expect(page.getByText(/@/)).toHaveCount(0);
});

for (const who of ["someone else", "nobody signed in"] as const) {
  test(`${who} gets "Page not found"`, async ({ page }) => {
    const api = new MockApi();
    if (who === "someone else") api.signedIn(finishedSettings());
    api.adminEmail = "admin@example.com";
    await api.install(page);
    await page.goto("/stats");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Page not found");
    await expect(page.getByText("Signed up")).toHaveCount(0);
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
