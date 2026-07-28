import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const output = "test-results/screenshots/customer-ui1";
const profile = { customer_id: "customer-preview", account_status: "ACTIVE", telegram_user_id: 100, username: "drping", account_username: null, first_name: "کاربر آزمایشی با نام بسیار طولانی برای بررسی چیدمان فارسی", last_name: null, language_code: "fa", created_at: "2026-01-01T00:00:00Z", last_seen_at: null, current_session_id: "session-preview" };

async function mockAuthenticated(page: Page): Promise<void> {
  await page.route("**/api/v1/customer/auth/**", route => {
    const path = new URL(route.request().url()).pathname;
    const body = path.endsWith("/capabilities") ? { password_login: false, public_registration: false, telegram_login: true, telegram_linking: false, web_credential_enrollment: false, email_recovery: false, telegram_recovery: false, recovery_codes: false } : path.endsWith("/me") ? profile : path.endsWith("/sessions") ? [] : {};
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
}

test.beforeAll(async () => mkdir(output, { recursive: true }));
for (const scenario of [
  { name: "home-360-dark", width: 360, height: 800, theme: "dark" },
  { name: "home-390-light", width: 390, height: 844, theme: "light" },
  { name: "home-430-dark", width: 430, height: 932, theme: "dark" },
  { name: "home-768-dark", width: 768, height: 1024, theme: "dark" },
  { name: "home-1440-dark", width: 1440, height: 900, theme: "dark" },
] as const) test(scenario.name, async ({ page }) => {
  await page.setViewportSize(scenario);
  await mockAuthenticated(page);
  await page.goto("/");
  await page.evaluate(theme => { document.documentElement.dataset.theme = theme; }, scenario.theme);
  await expect(page.getByRole("heading", { name: profile.first_name })).toBeVisible();
  await expect(page.getByText("هنوز سرویس فعالی ندارید")).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (scenario.width < 800) await expect(page.locator(".customer-bottom-nav a")).toHaveCount(5);
  await page.screenshot({ path: `${output}/${scenario.name}.png`, fullPage: true, animations: "disabled" });
});

test("loading, network error, and browser fallback states", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/v1/customer/auth/capabilities", route => new Promise(resolve => setTimeout(() => resolve(route.abort()), 5000)));
  await page.goto("/");
  await expect(page.locator(".loading-dashboard")).toBeVisible();
  await page.screenshot({ path: `${output}/loading.png`, animations: "disabled" });
  await page.unrouteAll({ behavior: "ignoreErrors" });
  await page.reload();
  await expect(page.getByRole("heading", { name: "ارتباط برقرار نشد" })).toBeVisible();
  await page.screenshot({ path: `${output}/network-error.png`, animations: "disabled" });
  await page.route("**/api/v1/customer/auth/capabilities", route => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ password_login: false, public_registration: false, telegram_login: true, telegram_linking: false, web_credential_enrollment: false, email_recovery: false, telegram_recovery: false, recovery_codes: false }) }));
  await page.route("**/api/v1/customer/auth/browser-bootstrap", route => route.fulfill({ status: 401, contentType: "application/json", body: "{}" }));
  await page.reload();
  await expect(page.getByRole("heading", { name: "تلگرام در دسترس نیست" })).toBeVisible();
  await page.screenshot({ path: `${output}/telegram-unavailable.png`, animations: "disabled" });
});
