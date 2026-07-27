import { afterEach, describe, expect, it, vi } from "vitest";
import { bootstrapCustomer, resetBootstrapForTests } from "../auth/bootstrap";
import { createTelegramAdapter } from "../telegram/adapter";

const SYNTHETIC_INIT_DATA = "query_id=synthetic-test-only&user=%7B%22id%22%3A42%7D&auth_date=1700000000&hash=not-a-real-hash";
const capabilities = { password_login: false, public_registration: false, telegram_login: true, telegram_linking: false, web_credential_enrollment: false, email_recovery: false, telegram_recovery: false, recovery_codes: false };
const profile = { customer_id: "synthetic-customer", account_status: "ACTIVE", telegram_user_id: 42, username: null, account_username: null, first_name: "Test", last_name: null, language_code: "fa", created_at: "2026-01-01T00:00:00Z", last_seen_at: null, current_session_id: "synthetic-session" };

function response(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

function fetcher(browserAuthenticated = false, requests: Array<{ url: string; body: string | null }> = []): typeof fetch {
  return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    requests.push({ url, body: typeof init?.body === "string" ? init.body : null });
    if (url.endsWith("/capabilities")) return response(200, capabilities);
    if (url.endsWith("/browser-bootstrap")) return response(browserAuthenticated ? 200 : 401, browserAuthenticated ? {} : { detail: "unauthorized" });
    if (url.endsWith("/telegram-mini-app")) return response(200, {});
    if (url.endsWith("/me")) return response(200, profile);
    if (url.endsWith("/sessions")) return response(200, []);
    throw new Error(`Unexpected synthetic request: ${url}`);
  }) as typeof fetch;
}

function installTelegram(initData: string, version = "8.0"): { ready: ReturnType<typeof vi.fn>; expand: ReturnType<typeof vi.fn> } {
  const ready = vi.fn();
  const expand = vi.fn();
  vi.stubGlobal("window", { Telegram: { WebApp: { initData, version, ready, expand } } });
  return { ready, expand };
}

afterEach(() => {
  resetBootstrapForTests();
  vi.unstubAllGlobals();
});

describe("official Telegram bridge adapter and bootstrap", () => {
  it("reads raw initData unchanged from an available bridge", () => {
    installTelegram(SYNTHETIC_INIT_DATA);
    const adapter = createTelegramAdapter();
    expect(adapter.isAvailable()).toBe(true);
    expect(adapter.getInitData()).toBe(SYNTHETIC_INIT_DATA);
  });

  it("returns TELEGRAM_UNAVAILABLE when Telegram is absent", async () => {
    vi.stubGlobal("window", {});
    expect((await bootstrapCustomer(createTelegramAdapter(), fetcher())).state).toBe("TELEGRAM_UNAVAILABLE");
  });

  it("returns UNAUTHORIZED for empty bridge initData", async () => {
    installTelegram("");
    expect((await bootstrapCustomer(createTelegramAdapter(), fetcher())).state).toBe("UNAUTHORIZED");
  });

  it("rejects unsupported Telegram clients before login", async () => {
    installTelegram(SYNTHETIC_INIT_DATA, "5.9");
    expect((await bootstrapCustomer(createTelegramAdapter(), fetcher())).state).toBe("UNSUPPORTED_CLIENT");
  });

  it("submits valid synthetic initData and signals ready and expand", async () => {
    const calls: Array<{ url: string; body: string | null }> = [];
    const bridge = installTelegram(SYNTHETIC_INIT_DATA);
    expect((await bootstrapCustomer(createTelegramAdapter(), fetcher(false, calls))).state).toBe("AUTHENTICATED");
    const login = calls.find(({ url }) => url.endsWith("/telegram-mini-app"));
    expect(login).toBeDefined();
    expect(JSON.parse(login?.body ?? "{}").init_data).toBe(SYNTHETIC_INIT_DATA);
    expect(bridge.expand).toHaveBeenCalledOnce();
    expect(bridge.ready).toHaveBeenCalledOnce();
  });

  it("preserves browser-session authentication without Telegram", async () => {
    vi.stubGlobal("window", {});
    expect((await bootstrapCustomer(createTelegramAdapter(), fetcher(true))).state).toBe("AUTHENTICATED");
  });
});
