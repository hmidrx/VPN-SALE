export type PaymentPurpose = "WALLET_TOPUP" | "ORDER_PAYMENT";
export type PaymentStatus = "REQUIRES_CUSTOMER_ACTION" | "REQUIRES_VERIFICATION" | "PROCESSING" | "SUCCEEDED" | "FAILED" | "CANCELLED" | "EXPIRED" | "RECONCILIATION_REQUIRED";
export type PaymentMethod = { code:string; display_name:string; description?:string; icon_kind:string; minimum_amount_rial:number; maximum_amount_rial:number; availability:"AVAILABLE"|"UNAVAILABLE" };
export type PaymentAction = { intent_reference:string; status:PaymentStatus; action_type:"REDIRECT"; action_url:string|null; expires_at:string; allowed_hosts?:string[] };
export type PaymentIntent = { reference:string; payment_reference?:string; purpose?:PaymentPurpose; method_label?:string; method_kind?:string; amount_rial?:number; currency?:"IRR"; status:PaymentStatus; created_at?:string; expires_at?:string; succeeded_at?:string|null; failed_at?:string|null; cancelled_at?:string|null; order_reference?:string|null; invoice_reference?:string|null; wallet_transaction_reference?:string|null; settlement_result?:Record<string,unknown>|null; failure_category?:string|null; correlation_id?:string|null; can_cancel?:boolean; can_retry?:boolean };
export type Page<T> = { items:T[]; next_cursor:string|null };
export type PaymentError = { code:string; message:string; retryAfter?:string|null; correlationId?:string };
