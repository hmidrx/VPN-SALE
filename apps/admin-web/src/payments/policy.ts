export const paymentPermissions = { methodsRead:'payment_methods.read', methodsManage:'payment_methods.manage', paymentsRead:'payments.read', webhooksRead:'payment_webhooks.read', webhooksRetry:'payment_webhooks.retry', auditRead:'audit.read', securityRead:'security_events.read', ledgerRead:'ledger.read' } as const;
export const paymentNav = [
 {href:'/management/payments',label:'عملیات پرداخت',permission:paymentPermissions.paymentsRead},
 {href:'/management/payment-methods',label:'روش‌های پرداخت',permission:paymentPermissions.methodsRead},
 {href:'/management/payment-intents',label:'نیت‌های پرداخت',permission:paymentPermissions.paymentsRead},
 {href:'/management/payment-webhooks',label:'صندوق وبهوک',permission:paymentPermissions.webhooksRead},
];
export function can(perms: readonly string[]|undefined, p:string): boolean { return Boolean(perms?.includes(p)); }
