import React from "react";

import { SupportNavigationLabel } from "../support/SupportNavigationLabel";

export type CustomerNavigationItem = {
  label: React.ReactNode;
  href: string;
  page: "home" | "services" | "wallet" | "support" | "profile";
  icon: React.ReactElement;
};

function Icon({ path }: { path: string }): React.ReactElement {
  return <svg aria-hidden="true" viewBox="0 0 24 24"><path d={path} fill="none" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" /></svg>;
}

export const customerNavigation: readonly CustomerNavigationItem[] = [
  { label: "خانه", href: "/app", page: "home", icon: <Icon path="M3 11.5 12 4l9 7.5V21h-6v-6H9v6H3z" /> },
  { label: "سرویس‌ها", href: "/services", page: "services", icon: <Icon path="M5 5h14v6H5zM5 15h14v4H5zM8 8h.01M8 17h.01" /> },
  { label: "کیف پول", href: "/wallet", page: "wallet", icon: <Icon path="M4 7a3 3 0 0 1 3-3h11v16H6a2 2 0 0 1-2-2zm0 1h14m-5 5h7v4h-7z" /> },
  { label: <SupportNavigationLabel />, href: "/support", page: "support", icon: <Icon path="M5 13v-1a7 7 0 0 1 14 0v1m-14-1v5h3v-5H5Zm14 0v5h-3v-5h3Z" /> },
  { label: "حساب", href: "/profile", page: "profile", icon: <Icon path="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" /> },
] as const;

export const accountNavigation = [
  { label: "امنیت", href: "/security" },
  { label: "نشست‌ها", href: "/sessions" },
  { label: "پشتیبانی", href: "/support" },
  { label: "تنظیمات", href: "/profile" },
] as const;
