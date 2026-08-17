"use client";

import { getSupportUnreadSummary } from "./api";

type Listener = () => void;

let snapshot = 0;
let listeners = new Set<Listener>();
let timer: number | null = null;
let controller: AbortController | null = null;
let refreshing = false;

function emit(value: number): void {
  if (snapshot === value) return;
  snapshot = value;
  for (const listener of listeners) listener();
}

export function getSupportUnreadSnapshot(): number {
  return snapshot;
}

export function getSupportUnreadServerSnapshot(): number {
  return 0;
}

export async function refreshSupportUnreadStore(): Promise<void> {
  if (refreshing) return;
  refreshing = true;
  try {
    const summary = await getSupportUnreadSummary(controller?.signal);
    if (!controller?.signal.aborted) emit(summary.total_unread);
  } catch {
    // Navigation unread state is supplemental and should fail quietly on transient errors.
  } finally {
    refreshing = false;
  }
}

function start(): void {
  if (typeof window === "undefined" || timer !== null) return;
  controller = new AbortController();
  void refreshSupportUnreadStore();
  timer = window.setInterval(() => {
    if (document.visibilityState === "visible") void refreshSupportUnreadStore();
  }, 30_000);
}

function stop(): void {
  if (listeners.size > 0) return;
  if (timer !== null) window.clearInterval(timer);
  timer = null;
  controller?.abort();
  controller = null;
  refreshing = false;
}

export function subscribeSupportUnread(listener: Listener): () => void {
  listeners.add(listener);
  start();
  return () => {
    listeners.delete(listener);
    stop();
  };
}
