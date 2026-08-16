import { afterEach, describe, expect, it, vi } from "vitest";
import { clearAuthMemory, setAccessToken } from "../auth/token-store";
import {
  getConnectionQr,
  issueServiceSubscription,
  resolveSubscriptionUrl,
  ServiceRequestError,
} from "../services";

afterEach(() => {
  vi.unstubAllGlobals();
  clearAuthMemory();
});

describe("customer service delivery request boundary", () => {
  it("issues a subscription exactly once with in-memory bearer auth", async () => {
    const token = "a".repeat(43);
    const fetcher = vi.fn(async () =>
      new Response(
        JSON.stringify({
          service_reference: "svc-public-test",
          status: "ACTIVE",
          stable_urls: { base64: `/subscriptions/${token}` },
          token_visible_once: token,
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetcher);
    setAccessToken("memory-only-access-token");

    await issueServiceSubscription("svc-public-test");

    expect(fetcher).toHaveBeenCalledTimes(1);
    const [input, init] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toContain(
      "/api/v1/customer/delivery/services/svc-public-test/subscription",
    );
    expect(init?.method).toBe("POST");
    expect(init?.credentials).toBe("include");
    expect(init?.cache).toBe("no-store");
    expect(new Headers(init?.headers).get("authorization")).toBe(
      "Bearer memory-only-access-token",
    );
  });

  it("does not retry an ambiguous subscription mutation", async () => {
    const fetcher = vi.fn(async () => {
      throw new TypeError("network unavailable");
    });
    vi.stubGlobal("fetch", fetcher);

    await expect(issueServiceSubscription("svc-public-test")).rejects.toEqual(
      expect.objectContaining<ServiceRequestError>({ status: 0 }),
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("accepts only strict relative subscription paths", () => {
    const token = "b".repeat(43);
    expect(
      resolveSubscriptionUrl(
        `/subscriptions/${token}/sing-box`,
        "https://customer.example.test",
      ),
    ).toBe(`https://customer.example.test/subscriptions/${token}/sing-box`);
    expect(() =>
      resolveSubscriptionUrl(
        `https://attacker.example/subscriptions/${token}`,
        "https://customer.example.test",
      ),
    ).toThrow("unsafe_subscription_path");
  });

  it("sends QR payload in a header instead of the URL", async () => {
    const payload = ["vless", "://", "runtime-only", "@example.test:443"].join("");
    const fetcher = vi.fn(async () =>
      new Response(new Uint8Array([137, 80, 78, 71]), {
        status: 200,
        headers: { "content-type": "image/png" },
      }),
    );
    vi.stubGlobal("fetch", fetcher);

    const image = await getConnectionQr(payload);
    expect(image.type).toBe("image/png");
    expect(fetcher).toHaveBeenCalledTimes(1);
    const [input, init] = fetcher.mock.calls[0] ?? [];
    expect(String(input)).toContain("/api/v1/customer/delivery/qr");
    expect(String(input)).not.toContain(payload);
    expect(new Headers(init?.headers).get("payload")).toBe(payload);
  });
});
