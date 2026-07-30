import React from "react";
import { loadCustomerConfig } from "../config/public-config";
import { EmptyState, PageHeader, PageShell, PremiumCard } from "../components/customer-ui";

export function CustomerSupportHome(): React.ReactElement {
  const botUsername = loadCustomerConfig().botUsername;
  return <PageShell labelledBy="page-title">
    <PageHeader title="پشتیبانی" subtitle="برای پرسش‌ها و پیگیری درخواست‌ها همراه شما هستیم." />
    {botUsername ? <PremiumCard className="support-entry"><span className="support-entry__icon" aria-hidden="true">◌</span><div><h2>گفت‌وگو با پشتیبانی</h2><p>پیام خود را در تلگرام ارسال کنید. هیچ اطلاعات حساسی به نشانی افزوده نمی‌شود.</p></div><a className="ui-button" href={`https://t.me/${botUsername}`} rel="noreferrer">باز کردن پشتیبانی</a></PremiumCard> : <EmptyState title="پشتیبانی در دسترس نیست" description="راه ارتباطی هنوز تنظیم نشده است. کمی بعد دوباره بررسی کنید." />}
  </PageShell>;
}
