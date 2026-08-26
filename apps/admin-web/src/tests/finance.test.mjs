import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
const src = (p) => readFileSync(new URL(p, import.meta.url), 'utf8');
const files = ['../finance/api.ts','../finance/money.ts','../finance/idempotency.ts','../finance/validation.ts','../finance/error-map.ts','../components/FinanceShell.tsx','../finance/permissions.ts'].map(src).join('\n');
for (const needle of ['wallets.read','wallets.adjust','wallets.freeze','wallets.policy.manage','ledger.read','ledger.reconcile','Idempotency-Key','cache:\'no-store\'','formatRial','formatToman','journalTotals','JOURNAL_NOT_BALANCED','INSUFFICIENT_AVAILABLE_BALANCE']) if (!files.includes(needle)) throw new Error(`missing finance invariant ${needle}`);
if (/localStorage|sessionStorage|IndexedDB|console\.log\(|set balance|set-balance|payment gateway|provider instance|invoice|order route/i.test(files)) throw new Error('forbidden financial persistence or out-of-scope wording in finance modules');
const appRoot = fileURLToPath(new URL('../../app/management', import.meta.url));
function walk(dir){ return readdirSync(dir).flatMap(n=>{const p=join(dir,n); return statSync(p).isDirectory()?walk(p):[p];}); }
const pages = walk(appRoot).filter(p=>p.endsWith('page.tsx')).map(p=>readFileSync(p,'utf8')).join('\n') + files;
for (const needle of ['نمای کلی مالی','کشف کیف‌پول','جزئیات کیف‌پول','اعتبار دستی','بدهی دستی','مسدودسازی کیف‌پول','کاوشگر دفترکل','جزئیات ژورنال','برگشت جبرانی','اعتبارها و انقضا','رزروهای کیف‌پول','سیاست نسخه‌دار کیف‌پول','تطبیق و تعمیر پروجکشن']) if(!pages.includes(needle)) throw new Error(`missing route page ${needle}`);
for (const needle of ['قابل استفاده','ثبت‌شده','رزرو','ریال','تومان','Debit','Credit','read-only','cursor','projection','مرکز امنیت']) if(!pages.includes(needle)) throw new Error(`missing UX coverage ${needle}`);
const docs = src('../../../../docs/milestones/MILESTONE_3_A2B_PLAN.md');
for (const needle of ['Page inventory','API coverage','wallets.adjust','Accounting','Mermaid','Non-goals','Acceptance criteria']) if(!docs.includes(needle)) throw new Error(`missing plan coverage ${needle}`);
