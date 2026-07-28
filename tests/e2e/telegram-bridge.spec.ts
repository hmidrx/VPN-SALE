import { expect, test, type Page } from "@playwright/test";

const SYNTHETIC_INIT_DATA = "query_id=synthetic-e2e-only&user=%7B%22id%22%3A42%7D&auth_date=1700000000&hash=not-a-real-hash";
const capabilities = { password_login: false, public_registration: false, telegram_login: true, telegram_linking: false, web_credential_enrollment: false, email_recovery: false, telegram_recovery: false, recovery_codes: false };
const profile = { customer_id: "synthetic-customer", account_status: "ACTIVE", telegram_user_id: 42, username: null, account_username: null, first_name: "Test", last_name: null, language_code: "fa", created_at: "2026-01-01T00:00:00Z", last_seen_at: null, current_session_id: "synthetic-session" };

async function mockCustomerApi(page: Page): Promise<string[]> {
  const loginBodies: string[] = [];
  await page.route("https://telegram.org/js/telegram-web-app.js?63", (route) => route.fulfill({ contentType: "application/javascript", body: "/* official bridge isolated in this deterministic test */" }));
  await page.route("**/api/v1/customer/auth/**", async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith("/capabilities")) return route.fulfill({ json: capabilities });
    if (path.endsWith("/browser-bootstrap")) return route.fulfill({ status: 401, json: { detail: "unauthorized" } });
    if (path.endsWith("/telegram-mini-app")) { loginBodies.push(route.request().postData() ?? ""); return route.fulfill({ json: {} }); }
    if (path.endsWith("/me")) return route.fulfill({ json: profile });
    if (path.endsWith("/sessions")) return route.fulfill({ json: [] });
    return route.abort();
  });
  return loginBodies;
}

test("ordinary browser reports Telegram unavailable", async ({ page }) => {
  await mockCustomerApi(page);
  await page.goto("/");
  await expect(page.getByText("ورود فقط از مینی‌اپ تلگرام فعال است.")).toBeVisible();
});

test("simulated Telegram bridge logs in and calls ready and expand without rendering initData", async ({ page }) => {
  const loginBodies = await mockCustomerApi(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript((initData) => {
    (window as typeof window & { __bridgeCalls: string[]; Telegram: unknown }).__bridgeCalls = [];
    (window as typeof window & { Telegram: unknown }).Telegram = { WebApp: { initData, version: "8.0", ready: () => (window as typeof window & { __bridgeCalls: string[] }).__bridgeCalls.push("ready"), expand: () => (window as typeof window & { __bridgeCalls: string[] }).__bridgeCalls.push("expand") } };
  }, SYNTHETIC_INIT_DATA);
  await page.goto("/");
  const navigation = page.getByRole("navigation", { name: "ناوبری اصلی مشتری" });
  await expect(navigation).toBeVisible();
  await expect(navigation.getByRole("link")).toHaveCount(5);
  await expect(page.getByRole("heading", { name: "Test" })).toBeVisible();
  expect(loginBodies).toHaveLength(1);
  expect(JSON.parse(loginBodies[0]).init_data).toBe(SYNTHETIC_INIT_DATA);
  expect(await page.evaluate(() => (window as typeof window & { __bridgeCalls: string[] }).__bridgeCalls)).toEqual(["expand", "ready"]);
  await expect(page.locator("body")).not.toContainText(SYNTHETIC_INIT_DATA);
});

test("simulated Telegram bridge with empty initData is unauthorized", async ({ page }) => {
  const loginBodies = await mockCustomerApi(page);
  await page.addInitScript(() => { (window as typeof window & { Telegram: unknown }).Telegram = { WebApp: { initData: "", version: "8.0", ready() {}, expand() {} } }; });
  await page.goto("/");
  await expect(page.getByText("دسترسی شما معتبر نیست.")).toBeVisible();
  expect(loginBodies).toHaveLength(0);
});
