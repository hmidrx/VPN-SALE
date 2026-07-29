import {expect, test} from '@playwright/test';

test('manual card transfer is premium, Toman-only, and mobile safe', async ({page}) => {
  await page.setViewportSize({width: 360, height: 780});
  await page.goto('/ui-preview/manual-topup');
  await expect(page.getByRole('heading', {name: 'افزایش موجودی کارت‌به‌کارت'})).toBeVisible();
  await expect(page.getByText('حداقل مبلغ ۱۰۰٬۰۰۰ تومان')).toBeVisible();
  await expect(page.getByText('دریافت اطلاعات کارت از پشتیبانی')).toBeVisible();
  await expect(page.getByRole('button', {name: /۲٬۰۰۰٬۰۰۰/})).toBeVisible();
  await expect(page.getByText(/ریال/)).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText(/\b\d{16}\b/);
  await expect(page.locator('body')).not.toContainText(/IBAN|شبا|شماره کارت/);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  expect(overflow).toBe(false);
});
