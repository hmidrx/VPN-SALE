export type Order = { order_reference:string; checkout_reference?:string|null; invoice_reference?:string|null; status:string; financial_status:string; fulfillment_status:string; final_amount_rial:number; currency:"IRR"; created_at:string; paid_at?:string|null; cancelled_at?:string|null; snapshot:Record<string, unknown> };
export type InvoiceLine = { line_type:string; description:string; quantity:number; unit_amount_rial:number; line_subtotal_rial:number; position:number };
export type Invoice = { invoice_reference:string; order_reference:string; status:string; currency:"IRR"; subtotal_rial:number; adjustment_total_rial:number; discount_total_rial:number; tax_total_rial:number; payable_total_rial:number; paid_total_rial:number; issued_at:string; due_at:string; paid_at?:string|null; cancelled_at?:string|null; lines:InvoiceLine[] };
export type CheckoutResult = { checkout:{checkout_reference:string; status:string; reservation_amount_rial?:number; expires_at?:string}; order:Order; invoice:Invoice };
export type TimelineEvent = { event_code:string; occurred_at:string; actor_type?:string; metadata?:Record<string, unknown> };
export type Page<T> = { items:T[]; next_cursor:string|null };
export type CommerceError = { code:string; message:string; correlationId?:string; retryAfter?:string|null };
