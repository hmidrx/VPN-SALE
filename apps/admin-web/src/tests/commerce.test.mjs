import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const src = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const files = ['../commerce/api.ts','../commerce/types.ts','../commerce/validation.ts','../commerce/format.ts','../commerce/idempotency.ts','../commerce/policy.ts','../components/CommerceShell.tsx','../i18n/commerce.ts'].map(src).join('\n');
for (const needle of ['orders.read','orders.cancel','invoices.read','checkout.read','wallets.read','ledger.read','ledger.reconcile','Idempotency-Key','cache:\'no-store\'','formatRial','formatToman','validateInvoice','INVOICE_AMOUNT_MISMATCH','safeMetadata','CommerceIdempotencyController']) if (!files.includes(needle)) throw new Error(`missing commerce invariant ${needle}`);
if (/localStorage|sessionStorage|IndexedDB|console\.log\(|mark-paid|set balance|set-balance|payment gateway|provider instance|server IP|subscription URI/i.test(files)) throw new Error('forbidden commerce persistence or out-of-scope control in commerce modules');
const appRoot = fileURLToPath(new URL('../../app/management', import.meta.url));
function walk(dir){ return readdirSync(dir).flatMap(n=>{const p=join(dir,n); return statSync(p).isDirectory()?walk(p):[p];}); }
const pages = walk(appRoot).filter(p=>p.endsWith('page.tsx')).map(p=>readFileSync(p,'utf8')).join('\n') + files;
for (const needle of ['/management/commerce','کشف و فیلتر سفارش‌ها','جزئیات سفارش','Commercial snapshot','timeline append-only','بازرسی checkout session','کشف فاکتورهای غیرقابل تغییر','جزئیات فاکتور immutable','Invoice-line expanded view','بازرسی wallet-payment','بازرسی reservation کیف‌پول','تطبیق read-only سفارش','Commercial inconsistency detail','بازرسی fulfillment outbox','جزئیات رویداد اوت‌باکس']) if(!pages.includes(needle)) throw new Error(`missing route page ${needle}`);
for (const needle of ['READY_FOR_FULFILLMENT','تحویل‌شده نیست','READY','تأمین نشده','QUEUED','موفق نیست','original capture immutable','compensating_wallet_refund','dry-run reconciliation','ORDER_INVOICE_AMOUNT_MISMATCH','DUPLICATE_SUCCESSFUL_CAPTURE','provider/server/inbound/credential/subscription payload','مرکز امنیت','financial audit activity']) if(!pages.includes(needle)) throw new Error(`missing UX invariant ${needle}`);
const docs = src('../../../../docs/milestones/MILESTONE_3_B2B_PLAN.md');
for (const needle of ['Page inventory','API coverage','Permission model','State separation','Administrator cancellation policy','Wallet refund presentation','Immutable invoice policy','Reconciliation workflow','Outbox inspection policy','Security boundaries','Accessibility','Non-goals','Acceptance criteria','Mermaid']) if(!docs.includes(needle)) throw new Error(`missing plan coverage ${needle}`);
