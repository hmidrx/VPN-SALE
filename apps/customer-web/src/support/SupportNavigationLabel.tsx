"use client";

import React from "react";

import styles from "./SupportNavigationLabel.module.css";
import {
  getSupportUnreadServerSnapshot,
  getSupportUnreadSnapshot,
  subscribeSupportUnread,
} from "./unread-store";

export function SupportNavigationLabel(): React.ReactElement {
  const unread = React.useSyncExternalStore(
    subscribeSupportUnread,
    getSupportUnreadSnapshot,
    getSupportUnreadServerSnapshot,
  );

  return <span className={styles.label}>
    <span>پشتیبانی</span>
    {unread > 0 ? <span className={styles.badge} aria-label={`${unread.toLocaleString("fa-IR")} پاسخ جدید`}>{unread.toLocaleString("fa-IR")}</span> : null}
  </span>;
}
