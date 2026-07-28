import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const output = "test-results/screenshots/services-ui41";
const profile = {
  customer_id: "customer-preview",
  account_status: "ACTIVE",
  telegram_user_id: 100,
  username: "preview",
  account_username: null,
  first_name: "کاربر آزمایشی",
  last_name: null,
  language_code: "fa",
  created_at: "2026-01-01T00:00:00Z",
  last_seen_at: null,
  current_session_id: "session-preview",
};
const capabilities = {
  password_login: false,
  public_registration: false,
  telegram_login: true,
  telegram_linking: false,
  web_credential_enrollment: false,
  email_recovery: false,
  telegram_recovery: false,
  recovery_codes: false,
};
const service = (
  reference: string,
  lifecycle: string,
  name: string,
  day: number,
) => ({
  service_reference: reference,
  display_name: name,
  lifecycle,
  lifecycle_label: lifecycle,
  created_at: `2026-07-${String(day).padStart(2, "0")}T10:00:00Z`,
  starts_at: "2026-07-02T10:00:00Z",
  activated_at: lifecycle === "ACTIVE" ? "2026-07-02T10:00:00Z" : null,
  expires_at: "2026-09-02T10:00:00Z",
  delivery_ready: false,
  required_attachment_count: 0,
  verified_attachment_count: 0,
  provisioning_progress: 0,
  safe_operational_message: "اطلاعات سرویس آماده نمایش است",
  entitlement: { traffic_quota_bytes: 53687091200, duration_days: 30, device_limit: 2, location_label: "تهران", quality_label: "ویژه" },
  usage: null,
});

async function mock(page: Page, services: ReturnType<typeof service>[]) {
  await page.route("https://telegram.org/js/telegram-web-app.js?63", (route) =>
    route.fulfill({ contentType: "application/javascript", body: "" }),
  );
  await page.addInitScript(() => {
    (window as typeof window & { Telegram: unknown }).Telegram = {
      WebApp: {
        colorScheme: "dark",
        version: "8.0",
        themeParams: {},
        initData: "",
        ready() {},
        expand() {},
        onEvent() {},
        offEvent() {},
      },
    };
  });
  await page.route("**/api/v1/customer/auth/**", (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        path.endsWith("/capabilities")
          ? capabilities
          : path.endsWith("/me")
            ? profile
            : path.endsWith("/sessions")
              ? []
              : {},
      ),
    });
  });
  await page.route("**/api/v1/customer/services", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(services),
    }),
  );
}

const emptyScenarios = [
  ["android-320-dark", 320, 700, "dark"],
  ["android-360-dark", 360, 800, "dark"],
  ["android-390-light", 390, 844, "light"],
  ["iphone-393-dark", 393, 852, "dark"],
  ["telegram-desktop-narrow", 768, 1024, "dark"],
  ["desktop-wide", 1440, 900, "light"],
] as const;
test.beforeAll(async () => mkdir(output, { recursive: true }));
for (const [name, width, height, theme] of emptyScenarios)
  test(`empty ${name}`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await mock(page, []);
    await page.goto("/services");
    await page.evaluate((value) => {
      document.documentElement.dataset.theme = value;
    }, theme);
    await expect(
      page.getByRole("heading", { name: "هنوز سرویسی ندارید" }),
    ).toBeVisible();
    await expect(
      page.getByRole("link", { name: "خرید سرویس جدید" }),
    ).toHaveCount(0);
    await expect(page.getByRole("link", { name: "مشاهده پلن‌ها" })).toHaveCount(
      1,
    );
    await expect(page.locator(".service-filters button")).toHaveCount(5);
    await expect(page.getByRole("button", { name: "متوقف" })).toBeVisible();
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    if (width < 800) {
      await page.evaluate(() =>
        scrollTo(0, document.documentElement.scrollHeight),
      );
      const boxes = await Promise.all([
        page.locator(".services-empty").boundingBox(),
        page.locator(".customer-bottom-nav").boundingBox(),
      ]);
      expect(boxes[0]).not.toBeNull();
      expect(boxes[1]).not.toBeNull();
      expect(boxes[0]!.y + boxes[0]!.height).toBeLessThanOrEqual(boxes[1]!.y);
    }
    await page.screenshot({
      path: `${output}/${name}.png`,
      fullPage: true,
      animations: "disabled",
    });
  });

test("populated services preserve safe presentation and refresh in place", async ({
  page,
}) => {
  const items = [
    service("svc-public-active", "ACTIVE", "سرویس همراه", 4),
    service("svc-public-preparing", "PROVISIONING", "سرویس خانه", 3),
    service("svc-public-stopped", "SUSPENDED", "سرویس متوقف", 2),
    service("svc-public-expired", "EXPIRED", "سرویس قدیمی", 1),
  ];
  await page.setViewportSize({ width: 360, height: 800 });
  await mock(page, items);
  await page.goto("/services");
  await expect(
    page.getByRole("link", { name: "خرید سرویس جدید" }),
  ).toBeVisible();
  await expect(page.locator(".service-filters button")).toHaveCount(5);
  const navigationEntries = await page.evaluate(
    () => performance.getEntriesByType("navigation").length,
  );
  await page.getByRole("button", { name: "تازه‌سازی سرویس‌ها" }).click();
  await expect(
    page.getByRole("button", { name: "تازه‌سازی سرویس‌ها" }),
  ).toBeEnabled();
  expect(
    await page.evaluate(
      () => performance.getEntriesByType("navigation").length,
    ),
  ).toBe(navigationEntries);
  expect(await page.locator("body").innerText()).not.toContain("ACTIVE");
  expect(await page.locator("body").innerText()).not.toContain(
    "svc-public-active",
  );
  await page.evaluate(() => scrollTo(0, document.documentElement.scrollHeight));
  const card = await page.locator(".service-card").last().boundingBox(),
    nav = await page.locator(".customer-bottom-nav").boundingBox();
  expect(card!.y + card!.height).toBeLessThanOrEqual(nav!.y);
  await page.screenshot({
    path: `${output}/mixed-services.png`,
    fullPage: true,
    animations: "disabled",
  });
});

test("one active service", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mock(page, [service("safe-reference-01", "ACTIVE", "سرویس شخصی", 2)]);
  await page.goto("/services");
  await expect(page.locator(".service-card")).toHaveCount(1);
  await page.screenshot({
    path: `${output}/one-active.png`,
    fullPage: true,
    animations: "disabled",
  });
});
