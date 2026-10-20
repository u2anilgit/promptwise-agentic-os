import { expect, test, type Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { STATE_DIR } from "../playwright.config";

const credential = () => readFileSync(join(STATE_DIR, ".promptwise", "dashboard_token"), "utf-8").trim();

async function signIn(page: Page) {
  await page.goto("/");
  await page.getByLabel("Credential").fill(credential());
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("link", { name: "Cost" })).toBeVisible();
}

test("a wrong credential is refused and nothing is shown", async ({ page }) => {
  await page.goto("/");
  await page.getByLabel("Credential").fill("not-the-credential");
  await page.getByRole("button", { name: "Continue" }).click();
  await expect(page.getByRole("alert")).toHaveText("That credential was not accepted.");
  await expect(page.getByRole("link", { name: "Cost" })).toHaveCount(0);
});

test("sign in, open Cost, and Builder mode hides raw token counts", async ({ page }) => {
  const violations: string[] = [];
  page.on("console", (m) => {
    if (m.type() === "error") violations.push(m.text());
  });
  await signIn(page);
  await page.getByRole("link", { name: "Cost" }).click();
  await expect(page).toHaveURL(/#\/cost$/);
  await expect(page.getByRole("heading", { name: "Cost and routing" })).toBeVisible();

  const byTier = page.getByRole("table", { name: "By tier" });
  await expect(byTier.getByRole("row", { name: /local-small/ })).toContainText("local");
  await expect(byTier.getByRole("row", { name: /cloud-premium/ })).toContainText("cloud");
  await expect(page.getByRole("table", { name: "By agent" }).getByRole("row", { name: /aider/ })).toBeVisible();
  await expect(page.getByText("2 task(s) agents named")).toBeVisible();

  await page.getByRole("button", { name: "Pro" }).click();
  await expect(page.getByText("Tokens in / out").first()).toBeVisible();
  await page.getByRole("button", { name: "Builder" }).click();
  await expect(page.getByRole("button", { name: "Builder" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("Tokens in / out")).toHaveCount(0);
  await expect(byTier.getByRole("row", { name: /cloud-premium/ })).toContainText("cloud"); // data unchanged

  await page.reload(); // mode is kept for the tab, the credential too
  await expect(page.getByRole("button", { name: "Builder" })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByRole("heading", { name: "Cost and routing" })).toBeVisible();
  expect(violations, "no console errors (CSP violations included)").toEqual([]);
});

test("audit view shows the seeded usage events with an intact chain", async ({ page }) => {
  await signIn(page);
  await page.getByRole("link", { name: "Audit" }).click();
  await expect(page.getByText("usage_recorded").first()).toBeVisible();
  await expect(page.getByText(/chain (intact|verified|ok)/i).first()).toBeVisible();
});

test("signing out clears the session", async ({ page }) => {
  await signIn(page);
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByLabel("Credential")).toBeVisible();
  await page.reload();
  await expect(page.getByLabel("Credential")).toBeVisible();
});
