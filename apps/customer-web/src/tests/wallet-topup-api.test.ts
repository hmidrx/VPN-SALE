import { afterEach, describe, expect, it, vi } from "vitest";
import { createWalletTopupIntent } from "../payments/api";
import { parseTomanInput, tomanToExactRial } from "../wallet/format";

afterEach(() => vi.unstubAllGlobals());
describe("wallet top-up request boundary", () => {
  it("sends exact Rial and preserves the idempotency key", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => new Response(JSON.stringify({ intent_reference: "public-test-reference", status: "REQUIRES_CUSTOMER_ACTION", action_type: "REDIRECT", action_url: "https://pay.example.test/action", expires_at: "2026-08-01T00:00:00Z", allowed_hosts: ["pay.example.test"] }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetcher);
    const rial = tomanToExactRial(parseTomanInput("۲۵۰٬۰۰۰"));
    await createWalletTopupIntent(rial, "safe-method", "idempotency-test-key");
    const init = fetcher.mock.calls[0]?.[1];
    expect(JSON.parse(String(init?.body))).toEqual({ amount_rial: 2_500_000, payment_method_code: "safe-method" });
    expect(new Headers(init?.headers).get("Idempotency-Key")).toBe("idempotency-test-key");
  });
});
