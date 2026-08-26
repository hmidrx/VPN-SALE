import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";

const output = "test-results/screenshots/wallet-ui51";
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
  manual_card_topups: true,
};
const summary = {
  currency: "IRR",
  status: "ACTIVE",
  posted_balance_rial: 2750000,
  reserved_balance_rial: 250000,
  available_balance_rial: 2500000,
  buckets: [
    { bucket_type: "CASH", customer_label: "cash", balance_rial: 2000000 },
    { bucket_type: "GIFT", customer_label: "gift", balance_rial: 750000 },
  ],
  updated_at: "2026-07-28T12:00:00Z",
  has_expiring_credit: false,
  active_reservation_count: 1,
};
const policy = {
  currency: "IRR",
  minimum_topup_amount_rial: 1000000,
  maximum_topup_amount_rial: 500000000,
  maximum_wallet_balance_rial: 2000000000,
  customer_wallet_operations_enabled: true,
  max_transaction_history_page_size: 20,
};
const transactions = {
  items: [
    {
      transaction_reference: "public-transaction-reference",
      type: "GIFT_CREDIT",
      direction: "INCOMING",
      amount_rial: 1000000,
      currency: "IRR",
      occurred_at: "2026-07-28T11:00:00Z",
      status: "POSTED",
    },
  ],
  next_cursor: null,
};
async function mock(page: Page): Promise<void> {
  await page.route("**/telegram-web-app.js?*", (route) =>
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
            : [],
      ),
    });
  });
  await page.route("**/api/v1/customer/wallet/**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(
        new URL(route.request().url()).pathname.endsWith("/policy")
          ? policy
          : new URL(route.request().url()).pathname.endsWith("/transactions")
            ? transactions
            : { items: [], next_cursor: null },
      ),
    }),
  );
  await page.route("**/api/v1/customer/wallet", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(summary),
    }),
  );
  await page.route("**/api/v1/customer/payments/methods?*", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", body: "[]" }),
  );
  await page.route("**/api/v1/customer/manual-topups**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
}
test.beforeAll(async () => mkdir(output, { recursive: true }));
for (const scenario of [
  { name: "overview-360-dark", path: "/wallet", width: 360, height: 800 },
  { name: "topup-393-dark", path: "/wallet/top-up", width: 393, height: 852 },
  { name: "overview-1280-dark", path: "/wallet", width: 1280, height: 800 },
] as const)
  test(scenario.name, async ({ page }) => {
    await page.setViewportSize(scenario);
    await mock(page);
    await page.goto(scenario.path);
    if (scenario.path === "/wallet/top-up") {
      await expect(
        page.getByRole("heading", { name: "افزایش موجودی کارت‌به‌کارت" }),
      ).toBeVisible();
    } else {
      await expect(
        page
          .getByRole("navigation", { name: "بخش‌های اصلی کیف پول" })
          .getByRole("link"),
      ).toHaveCount(3);
    }
    await expect(page.getByText("تومان").first()).toBeVisible();
    await expect(page.locator("body")).not.toContainText("ریال");
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${output}/${scenario.name}.png`,
      fullPage: true,
      animations: "disabled",
    });
  });
test("card-to-card top-up is concise and invalid amount never posts", async ({
  page,
}) => {
  let posts = 0;
  await mock(page);
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("manual-topups"))
      posts += 1;
  });
  await page.goto("/wallet/top-up");
  await expect(page.getByText("حداقل مبلغ ۱۰۰٬۰۰۰ تومان")).toBeVisible();
  await expect(
    page.getByRole("button", { name: "۲٬۰۰۰٬۰۰۰ تومان" }),
  ).toBeVisible();
  await expect(page.getByText("کارت‌به‌کارت", { exact: true })).toBeVisible();
  await page.getByLabel("مبلغ به تومان").fill("۹۹٬۹۹۹");
  await page.getByRole("button", { name: "ادامه و ایجاد درخواست" }).click();
  await expect(page.getByText("مبلغ باید حداقل ۱۰۰٬۰۰۰ تومان باشد.")).toBeVisible();
  await expect(page.locator("body")).not.toContainText(/زرین.?پال|پرداخت آنلاین/);
  expect(posts).toBe(0);
});

test("UI-5.2 editable Persian amount and bottom navigation clearance", async ({
  page,
}) => {
  let posts = 0;
  await page.setViewportSize({ width: 360, height: 800 });
  await mock(page);
  page.on("request", (request) => {
    if (request.method() === "POST" && request.url().includes("wallet-topups"))
      posts += 1;
  });
  await page.goto("/wallet/top-up");
  const amount = page.getByLabel("مبلغ به تومان");
  await page.getByRole("button", { name: "۱۰۰٬۰۰۰ تومان" }).click();
  await expect(amount).toHaveValue("۱۰۰٬۰۰۰");
  await expect(page.locator(".manual-presets [aria-pressed=true]")).toHaveCount(
    1,
  );
  await amount.fill("۱۰۰۰۰۱");
  await expect(amount).toHaveValue("۱۰۰٬۰۰۱");
  await expect(page.locator(".manual-presets [aria-pressed=true]")).toHaveCount(
    0,
  );
  const nav = page.locator(".customer-bottom-nav");
  const form = page.locator(".manual-create");
  await form.evaluate((element) => element.scrollIntoView({ block: "center" }));
  const [formBox, navBox] = await Promise.all([form.boundingBox(), nav.boundingBox()]);
  expect(formBox).not.toBeNull();
  expect(navBox).not.toBeNull();
  expect(formBox!.y).toBeLessThan(navBox!.y);
  expect(posts).toBe(0);
  await page.screenshot({
    path: `${output}/topup-360-selected-ui52.png`,
    fullPage: true,
    animations: "disabled",
  });
});

for (const viewport of [
  { name: "wide-1024", width: 1024, height: 768 },
  { name: "wide-1280", width: 1280, height: 800 },
  { name: "wide-1440", width: 1440, height: 900 },
  { name: "iphone-393", width: 393, height: 852 },
  { name: "telegram-desktop-narrow", width: 420, height: 720 },
] as const) {
  test(`UI-5.2 screenshot ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mock(page);
    await page.goto("/wallet/top-up");
    await page.getByRole("button", { name: "۲٬۰۰۰٬۰۰۰ تومان" }).click();
    await expect(page.getByLabel("مبلغ به تومان")).toHaveValue("۲٬۰۰۰٬۰۰۰");
    expect(
      await page.evaluate(
        () =>
          document.documentElement.scrollWidth <=
          document.documentElement.clientWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `${output}/${viewport.name}-ui52.png`,
      fullPage: true,
      animations: "disabled",
    });
  });
}

test("UI-5.2 transaction refresh and compact empty state", async ({ page }) => {
  await page.setViewportSize({ width: 420, height: 720 });
  await mock(page);
  await page.route("**/api/v1/customer/wallet/transactions**", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ items: [], next_cursor: null }),
    }),
  );
  await page.goto("/wallet/transactions");
  const refresh = page.getByRole("button", { name: "به‌روزرسانی تراکنش‌ها" });
  await expect(refresh).toBeVisible();
  const refreshBox = await refresh.boundingBox();
  expect(refreshBox!.height).toBeGreaterThanOrEqual(44);
  await expect(
    page.getByRole("heading", { name: "هنوز تراکنشی ندارید" }),
  ).toBeVisible();
  await expect(page.locator(".wallet-empty-action")).toBeVisible();
  await page.screenshot({
    path: `${output}/transactions-empty-narrow-ui52.png`,
    fullPage: true,
    animations: "disabled",
  });
});
