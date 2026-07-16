import type { TelegramAdapter } from "../telegram/adapter";
import { telegramLogin, getProfile, getSessions } from "./api-client";
import type { CustomerAuthState, CustomerProfile, CustomerSession } from "./types";
let bootstrapPromise: Promise<BootstrapResult> | null = null;
export type BootstrapResult = { state: CustomerAuthState; profile?: CustomerProfile; sessions?: CustomerSession[]; error?: string };
export async function bootstrapCustomer(adapter: TelegramAdapter, fetcher: typeof fetch = fetch): Promise<BootstrapResult> { if (bootstrapPromise) return bootstrapPromise; bootstrapPromise = run(adapter, fetcher).finally(() => { bootstrapPromise = null; }); return bootstrapPromise; }
async function run(adapter: TelegramAdapter, fetcher: typeof fetch): Promise<BootstrapResult> { if (!adapter.isAvailable()) return { state: "TELEGRAM_UNAVAILABLE" }; if (!adapter.isSupported()) return { state: "UNSUPPORTED_CLIENT" }; adapter.expand(); const initData = adapter.getInitData(); if (!initData.trim()) { adapter.ready(); return { state: "UNAUTHORIZED", error: "empty_init_data" }; } await telegramLogin(initData, fetcher); const [profile, sessions] = await Promise.all([getProfile(fetcher), getSessions(fetcher)]); adapter.ready(); return { state: "AUTHENTICATED", profile, sessions }; }
export function resetBootstrapForTests(): void { bootstrapPromise = null; }
