export class FinancialIdempotencyController { private key: string|null = null; get(): string { if(!this.key) this.key = crypto.randomUUID(); return this.key; } reset(): void { this.key = null; } changed(): void { this.reset(); } }
export function idempotencyHeaders(controller: FinancialIdempotencyController): HeadersInit { return { 'Idempotency-Key': controller.get() }; }
