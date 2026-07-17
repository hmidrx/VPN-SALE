import { correlationId } from "../auth/api-client";
import { getAccessToken } from "../auth/token-store";
import { loadCustomerConfig } from "../config/public-config";
import type { Category, PricePreview, ProductDetail, ProductOptions, ProductSummary, Quote, QuoteSelection } from "./types";
type Fetcher = typeof fetch;
const config = loadCustomerConfig();
const cache = new Map<string, Promise<unknown>>();
function authHeaders(extra?: HeadersInit): Headers { const h = new Headers(extra); h.set("content-type", "application/json"); h.set("x-request-id", correlationId()); const token = getAccessToken(); if (token) h.set("authorization", `Bearer ${token}`); return h; }
async function json<T>(path: string, init: RequestInit = {}, fetcher: Fetcher = fetch): Promise<T> { const r = await fetcher(`${config.apiBaseUrl}/api/v1/catalog${path}`, { ...init, headers: authHeaders(init.headers), credentials: "include" }); if (!r.ok) throw new Error(r.status === 429 ? "rate_limited" : r.status >= 500 ? "service_unavailable" : "catalog_error"); return r.json() as Promise<T>; }
function dedupe<T>(key: string, load: () => Promise<T>): Promise<T> { if (!cache.has(key)) cache.set(key, load().finally(() => cache.delete(key))); return cache.get(key) as Promise<T>; }
export async function listCategories(locale = "fa", signal?: AbortSignal): Promise<Category[]> { const page = await dedupe<{ items: Category[] }>(`categories:${locale}`, () => json(`/categories?locale=${locale}`, { signal })); return page.items; }
export async function listProducts(locale = "fa", signal?: AbortSignal): Promise<ProductSummary[]> { const page = await dedupe<{ items: ProductSummary[] }>(`products:${locale}`, () => json(`/products?locale=${locale}`, { signal })); return page.items; }
export const getProduct = (id: string, locale = "fa", signal?: AbortSignal): Promise<ProductDetail> => json(`/products/${encodeURIComponent(id)}?locale=${locale}`, { signal });
export const getProductOptions = (id: string, signal?: AbortSignal): Promise<ProductOptions> => json(`/products/${encodeURIComponent(id)}/options`, { signal });
export const previewPrice = (selection: QuoteSelection, signal?: AbortSignal): Promise<PricePreview> => json("/quotes/preview", { method: "POST", body: JSON.stringify(selection), signal });
export const createQuote = (selection: QuoteSelection, idempotencyKey: string): Promise<Quote> => json("/quotes", { method: "POST", body: JSON.stringify(selection), headers: { "Idempotency-Key": idempotencyKey } });
export const getQuote = (reference: string, signal?: AbortSignal): Promise<Quote> => json(`/quotes/${encodeURIComponent(reference)}`, { signal });
