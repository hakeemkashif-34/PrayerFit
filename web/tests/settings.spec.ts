import { expect, test } from "@playwright/test";
import { finishedSettings, MockApi } from "./mock-api";

test("the settings page shows every saved setting with an Edit button", async ({ page }) => {
  await new MockApi().signedIn(finishedSettings()).install(page);
  await page.goto("/");

  await expect(page.getByRole("heading", { name: "Your prayers" })).toBeVisible();
  await expect(page.getByText("Signed in as hakeem@example.com")).toBeVisible();
  for (const name of ["location", "prayer time method", "main masjid", "prayers at the masjid", "jumuah masjids"]) {
    await expect(page.getByRole("button", { name: `Edit ${name}` })).toBeVisible();
  }
  await expect(page.getByText("ISNA, Standard Asr")).toBeVisible();
  await expect(page.getByText("Monday: Dhuhr, Isha")).toBeVisible();
  await expect(page.getByText("Saturday: all at home")).toBeVisible();
  // The page shows OpenStreetMap data, so the credit is in its footer.
  await expect(page.getByRole("contentinfo").getByRole("link", { name: "© OpenStreetMap contributors" })).toBeVisible();
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

test("a save that can't reach Google offers Sign in again", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.route("**/api/settings/methods", (route) =>
    route.fulfill({
      json: {
        settings: finishedSettings(),
        calendar: { status: "sign_in_needed", sent: 0, waiting: 69, message: "Saved. Sign in again so your calendar can update." },
      },
    }),
  );
  await page.goto("/");

  await page.getByRole("button", { name: "Edit prayer time method" }).click();
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByRole("status")).toContainText("Saved. Sign in again so your calendar can update.");
  await expect(page.getByRole("link", { name: "Sign in again" })).toHaveAttribute("href", "/auth/google/login");
});

test("editing the location picks a new place from the suggestions", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit location" }).click();
  await page.getByRole("combobox").pressSequentially("Robson", { delay: 30 });
  await page.getByRole("option", { name: "1 Robson Street, Vancouver, British Columbia, Canada" }).click();

  expect(api.calls("PUT", "/api/settings/location")[0].body).toEqual({ query: "Robson", index: 0 });
  await expect(page.getByText("1 Robson Street, Vancouver, British Columbia, Canada")).toBeVisible();
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
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
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
  await page.getByRole("button", { name: "Change" }).click();
  await page.getByRole("combobox").pressSequentially("Stittsville", { delay: 30 });
  await page.getByRole("option", { name: /^Stittsville Masjid/ }).click();
  await expect(shortName).toHaveValue("");
  await page.getByRole("button", { name: "Save" }).click();

  expect(api.calls("PUT", "/api/settings/main-masjid")[0].body).toEqual({
    choice: "masjid", masjid_id: "22222222-2222-2222-2222-222222222222",
  });
});

test("I pray at home on the settings page moves every prayer home", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit main masjid" }).click();
  await page.getByRole("button", { name: "I pray at home" }).click();

  expect(api.calls("PUT", "/api/settings/main-masjid")[0].body).toEqual({ choice: "home" });
  await expect(page.getByRole("region", { name: "Main masjid" })).toContainText("I pray at home");
  await expect(page.getByRole("region", { name: "Prayers at the masjid" })).toHaveCount(0);
});

test("Jumuah masjids are added with the masjid search and can be removed", async ({ page }) => {
  const api = new MockApi().signedIn(finishedSettings());
  await api.install(page);
  await page.goto("/");

  await page.getByRole("button", { name: "Edit jumuah masjids" }).click();
  await page.getByRole("button", { name: "Remove Stittsville Masjid" }).click();
  await page.getByRole("combobox").pressSequentially("Toronto", { delay: 30 });
  await page.getByRole("option", { name: /^Kanata Masjid Toronto/ }).click();
  await page.getByRole("button", { name: "Save", exact: true }).click();

  expect(api.calls("PUT", "/api/settings/jumuah")[0].body).toEqual({
    masjid_ids: ["11111111-1111-1111-1111-111111111111", "33333333-3333-3333-3333-333333333333"],
  });
  await expect(page.getByRole("region", { name: "Jumuah masjids" })).toContainText("Kanata Masjid Toronto");
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
