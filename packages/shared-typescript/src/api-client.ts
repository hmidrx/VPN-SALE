export type HealthResponse = { status: string };
export async function getHealth(baseUrl: string): Promise<HealthResponse> { const r = await fetch(`${baseUrl}/health`); if (!r.ok) throw new Error("health request failed"); return r.json() as Promise<HealthResponse>; }

export type CatalogMoney = {
  amountMinor: number;
  currency: string;
};

export type CatalogProductSummary = {
  id: string;
  category_id: string;
  machine_code: string;
  display_order: number;
  name?: string;
  description?: string;
};

export type CatalogQuote = {
  quote_reference: string;
  product_id: string;
  product_version_id: string;
  operation: "NEW_PURCHASE" | "RENEWAL" | "TRAFFIC_ADDON" | "DURATION_EXTENSION";
  selected_options: Record<string, string | number | boolean>;
  price_list_version_id: string;
  currency: string;
  subtotal_minor: number;
  final_amount_minor: number;
  expires_at: string;
  status: "ACTIVE" | "EXPIRED" | "SUPERSEDED" | "CANCELLED" | "CONSUMED_RESERVED_FOR_FUTURE";
  pricing_engine_version: string;
};
