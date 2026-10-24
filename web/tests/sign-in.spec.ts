import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

test("signed-out users see Sign in with Google", async ({ page }) => {
  await new MockApi().install(page);
  await page.goto("/");

  const button = page.getByRole("link", { name: "Sign in with Google" });
  await expect(button).toBeVisible();
  await expect(button).toHaveAttribute("href", "/auth/google/login");
  await expect(page.getByText("Never Gmail")).toBeVisible();
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
  await page.getByRole("button", { name: "Edit prayer time method" }).click();

  api.failNext["/api/settings/methods"] = {
    status: 401,
    detail: { message: "Google sign-in expired. Sign in again.", reason: "google_sign_in_expired", login_url: "/auth/google/login" },
  };
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("link", { name: "Sign in again" })).toBeVisible();
});
