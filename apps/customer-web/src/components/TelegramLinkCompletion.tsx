"use client";

import React from "react";
import { Alert, Button, Card, PageHeader } from "@vpnsale/ui";
import { createTelegramWebApp } from "@vpnsale/telegram-webapp";
import { completeTelegramLink } from "../auth/api-client";

export function TelegramLinkCompletion(): React.ReactElement {
  const [state, setState] = React.useState<"working" | "done" | "failed">("working");
  React.useEffect(() => {
    const telegram = createTelegramWebApp();
    const challenge = telegram.startParam();
    const initData = telegram.rawInitData();
    if (!challenge || !initData) {
      setState("failed");
      return;
    }
    // This dedicated entry point deliberately completes linking before any ordinary
    // Telegram bootstrap can create a Telegram-only account.
    void completeTelegramLink(challenge, initData)
      .then(() => setState("done"))
      .catch(() => setState("failed"));
  }, []);
  return <main dir="rtl" className="customer"><Card><PageHeader title="اتصال امن تلگرام" />{state === "working" ? <Alert title="در حال بررسی" tone="warning">اطلاعات امضاشده تلگرام در حال بررسی است.</Alert> : state === "done" ? <><Alert title="اتصال انجام شد" tone="success">اکنون هر دو روش ورود به همین حساب متصل هستند.</Alert><a className="ui-button" href="/">ورود به حساب</a></> : <><Alert title="اتصال انجام نشد" tone="danger">درخواست نامعتبر یا منقضی است. از وب‌سایت دوباره تلاش کنید.</Alert><Button onClick={() => history.back()}>بازگشت</Button></>}</Card></main>;
}
