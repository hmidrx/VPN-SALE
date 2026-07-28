import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const output = "test-results/screenshots/catalog-ui3";
const profile = {
  customer_id: "customer-preview",
  account_status: "ACTIVE",
  telegram_user_id: 100,
  username: "preview",
  account_username: null,
  first_name: "کاربر",
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
const categories = [
  {
    id: "category-a",
    slug: "standard",
    display_order: 1,
    name: "اتصال روزمره",
    description: "برای وب‌گردی و استفاده روزانه",
  },
];
const products = [
  {
    id: "product-a",
    category_id: "category-a",
    machine_code: "STANDARD_A",
    display_order: 1,
    name: "پلن استاندارد ماهانه",
    description: "اتصال پایدار با گزینه‌های قابل انتخاب برای مصرف روزانه",
  },
  {
    id: "product-b",
    category_id: "category-a",
    machine_code: "STANDARD_B",
    display_order: 2,
    name: "پلن حرفه‌ای",
    description: "گزینه‌ای منعطف برای چند دستگاه و مصرف بیشتر",
  },
];

async function setup(page: Page, catalogProducts = products): Promise<void> {
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
    const body = path.endsWith("/capabilities")
      ? capabilities
      : path.endsWith("/me")
        ? profile
        : path.endsWith("/sessions")
          ? []
          : {};
    return route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(body),
    });
  });
  await page.route("**/api/v1/catalog/categories?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: categories }),
    }),
  );
  await page.route("**/api/v1/catalog/products?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: catalogProducts }),
    }),
  );
}

test.beforeAll(async () => mkdir(output, { recursive: true }));
for (const viewport of [
  { name: "android-dark", width: 390, height: 844 },
  { name: "iphone-light", width: 430, height: 932 },
  { name: "telegram-desktop", width: 1024, height: 768 },
  { name: "desktop-wide", width: 1440, height: 900 },
]) {
  test(`populated products ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await setup(page);
    await page.goto("/catalog/products");
    await expect(page.getByRole("heading", { name: "محصولات" })).toBeVisible();
    await expect(page.locator(".catalog-card")).toHaveCount(2);
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    const last = page.locator(".catalog-card-actions").last();
    await last.scrollIntoViewIfNeeded();
    await expect(last).toBeInViewport();
    await page.screenshot({
      path: `${output}/${viewport.name}.png`,
      fullPage: true,
      animations: "disabled",
    });
  });
}

test("empty, search, clear, and no-result states", async ({ page }) => {
  await page.setViewportSize({ width: 360, height: 800 });
  await setup(page, []);
  await page.goto("/catalog/products");
  await expect(
    page.getByRole("heading", { name: "هنوز پلنی برای نمایش وجود ندارد" }),
  ).toBeVisible();
  await expect(page.locator(".catalog-inline-state")).toBeVisible();
  await expect(page.locator(".catalog-content .state")).toHaveCount(0);
  await page.screenshot({
    path: `${output}/android-empty.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page.unroute("**/api/v1/catalog/products?**");
  await page.route("**/api/v1/catalog/products?**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: products }),
    }),
  );
  await page.reload();
  const search = page.getByPlaceholder("جست‌وجوی پلن یا سرویس");
  await search.fill("ناموجود");
  await expect(
    page.getByRole("heading", { name: "نتیجه‌ای پیدا نشد" }),
  ).toBeVisible();
  await page.screenshot({
    path: `${output}/no-results.png`,
    fullPage: true,
    animations: "disabled",
  });
  await page
    .locator(".catalog-inline-state")
    .getByRole("button", { name: "پاک‌کردن جست‌وجو" })
    .click();
  await expect(page.locator(".catalog-card")).toHaveCount(2);
  await search.fill("STANDARD");
  await page.screenshot({
    path: `${output}/populated-search.png`,
    fullPage: true,
    animations: "disabled",
  });
  await search.press("Escape");
  await expect(search).toHaveValue("");
});

test("customer-safe failure variants", async ({ page }) => {
  await page.setViewportSize({ width: 393, height: 852 });
  await setup(page);
  await page.unroute("**/api/v1/catalog/products?**");
  await page.route("**/api/v1/catalog/products?**", (route) =>
    route.fulfill({ status: 503, body: "internal_exception_secret" }),
  );
  await page.goto("/catalog/products");
  await expect(
    page.getByRole("heading", { name: "فروشگاه موقتاً در دسترس نیست" }),
  ).toBeVisible();
  await expect(page.getByText("internal_exception_secret")).toHaveCount(0);
  await page.screenshot({
    path: `${output}/service-unavailable.png`,
    fullPage: true,
    animations: "disabled",
  });
});
