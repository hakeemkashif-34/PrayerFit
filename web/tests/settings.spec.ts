import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

test("the settings page shows every saved setting with an Edit button", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Your prayers" })).toBeVisible();
  await expect(page.getByText("Signed in as hakeem@example.com")).toBeVisible();
  for (const name of ["address", "prayer time method", "main masjid", "prayers at the masjid", "jumuah masjids"]) {
    await expect(page.getByRole("button", { name: `Edit ${name}` })).toBeVisible();
  }
  await expect(page.getByText("ISNA, Standard Asr")).toBeVisible();
  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  await expect(page.getByText("Saturday: all at home")).toBeVisible();
});

test("editing a setting saves it and says what changed in the calendar", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayer time method" }).click();
  await page.getByRole("radio", { name: /Hanafi/ }).check();
  await page.getByRole("button", { name: "Save" }).click();

  expect(api.calls("PUT", "/api/settings/methods")[0].body).toEqual({ method: "isna", asr_method: "hanafi" });
  await expect(page.getByText("ISNA, Hanafi Asr")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Calendar updated. 3 events sent to Google.");
});

test("cancel leaves the setting as it was", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayers at the masjid" }).click();
  await page.getByLabel("Asr on Monday at the masjid").check();
  await page.getByRole("button", { name: "Cancel" }).click();

  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  expect(api.calls("PUT", "/api/settings/weekly")).toHaveLength(0);
});

test("picking a masjid after praying at home asks for the weekly grid", async ({ page }) => {
  const settings = { ...finishedSettings(), main_masjid_choice: "home" as const, main_masjid: null, weekly: [] };
  const api = new MockApi().signedIn(settings);
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("radio", { name: /Stittsville Masjid/ }).check();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("heading", { name: "Which prayers do you usually pray at Stittsville Masjid?" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Cancel" })).toHaveCount(0);
});

test("picking a different masjid clears the old short name", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  const shortName = page.getByLabel("Short name for your calendar (optional)");
  await expect(shortName).toHaveValue("KMA");
  await page.getByRole("radio", { name: /Stittsville Masjid/ }).check();
  await expect(shortName).toHaveValue("");
  await page.getByRole("button", { name: "Save" }).click();

  expect(api.calls("PUT", "/api/settings/main-masjid")[0].body).toEqual({
    choice: "masjid", masjid_id: "22222222-2222-2222-2222-222222222222",
  });
});

test("sign out calls the API and goes back to the sign-in screen", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Sign out" }).click();

  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
  expect(api.calls("POST", "/auth/logout")).toHaveLength(1);
  // Reloading stays signed out.
  await page.reload();
  await expect(page.getByRole("link", { name: "Sign in with Google" })).toBeVisible();
});
