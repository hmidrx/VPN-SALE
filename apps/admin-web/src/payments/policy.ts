export const paymentPermissions = { methodsRead:'payment_methods.read', methodsManage:'payment_methods.manage', paymentsRead:'payments.read', webhooksRead:'payment_webhooks.read', webhooksRetry:'payment_webhooks.retry', auditRead:'audit.read', securityRead:'security_events.read', ledgerRead:'ledger.read' } as const;
export const paymentNav = [
 {href:'/management/manual-topups',label:'صف رسیدهای کارت‌به‌کارت',permission:'manual_topups.read'},
 {href:'/management/manual-topups/destination',label:'شماره کارت مقصد',permission:'manual_topups.destination.read'},
 {href:'/management/finance',label:'کیف پول و دفترکل',permission:paymentPermissions.ledgerRead},
];
export function can(perms: readonly string[]|undefined, p:string): boolean { return Boolean(perms?.includes(p)); }
