// "Delete my account" at the bottom of Settings. The mock API's DELETE
// /api/account signs the user out, like the backend does.

import { expect, test, type Page } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

const WARNING =
  "This deletes your PrayerFit account, your settings, and the Prayers calendar from your Google Calendar. This can't be undone.";

async function openSettings(page: Page, api = new MockApi()) {
  await api.signedIn(finishedSettings()).install(page);
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
  return api;
}

const deleteButton = (page: Page) => page.getByRole("button", { name: "Delete my account" });

test("the button is at the very bottom, outlined in red", async ({ page }) => {
  await openSettings(page);
  const button = deleteButton(page);
  await expect(button).toBeVisible();
  // Below everything else on the page, including Sign out.
  const [del, signOut] = await Promise.all([button.boundingBox(), page.getByRole("button", { name: "Sign out" }).boundingBox()]);
  expect(del!.y).toBeGreaterThan(signOut!.y);
  const look = await button.evaluate((el) => {
    const s = getComputedStyle(el);
    return { border: s.borderTopColor, text: s.color, background: s.backgroundColor };
  });
  // Red outline and red text on no fill: careful, not inviting.
  expect(look).toEqual({ border: "rgb(163, 32, 32)", text: "rgb(163, 32, 32)", background: "rgba(0, 0, 0, 0)" });
});

test("it asks first, and Cancel leaves everything as it was", async ({ page }) => {
  const api = await openSettings(page);
  await deleteButton(page).click();
  const dialog = page.getByRole("alertdialog", { name: "Delete my account?" });
  await expect(dialog).toContainText(WARNING);
  await expect(dialog.getByRole("button", { name: "Delete my account" })).toBeVisible();
  // Cancel has focus, so a stray Enter deletes nothing.
  await expect(dialog.getByRole("button", { name: "Cancel" })).toBeFocused();
  await dialog.getByRole("button", { name: "Cancel" }).click();
  await expect(dialog).toHaveCount(0);
  expect(api.calls("DELETE", "/api/account")).toHaveLength(0);
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});

test("confirming deletes the account, signs out, and shows the landing page", async ({ page }) => {
  const api = await openSettings(page);
  await deleteButton(page).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete my account" }).click();
  await api.sent("DELETE", "/api/account", 1);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome to PrayerFit");
  await expect(page.getByRole("status")).toHaveText("Your account has been deleted.");
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
});

test("if Google couldn't be reached, it says how to remove the Prayers calendar", async ({ page }) => {
  const api = new MockApi();
  api.googleReachable = false;
  await openSettings(page, api);
  await deleteButton(page).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete my account" }).click();
  await expect(page.getByRole("status")).toHaveText(
    "Your account has been deleted." +
      "We couldn't reach Google, so the \"Prayers\" calendar may still be in your Google Calendar. You can delete it there yourself.",
  );
});

test("an error keeps them on Settings with the message", async ({ page }) => {
  const api = new MockApi();
  api.failNext["/api/account"] = { status: 500, detail: { message: "The server had a problem. Try again." } };
  await openSettings(page, api);
  await deleteButton(page).click();
  await page.getByRole("alertdialog").getByRole("button", { name: "Delete my account" }).click();
  await expect(page.getByRole("alertdialog").getByRole("alert")).toHaveText("The server had a problem. Try again.");
  await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();
});
