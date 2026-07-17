import { payFa } from '../i18n/payments';
import { paymentNav } from '../payments/policy';
import { ManagementShell, Tech } from './ManagementShell';
export function PaymentOpsShell({title,required,children}:{title:string;required?:string;children?:React.ReactNode}): React.ReactElement { return <ManagementShell title={title} eyebrow="کنسول عملیات پرداخت" required={required}><nav className="nav" aria-label="ناوبری عملیات پرداخت">{paymentNav.map(i=><a className="pill" href={i.href} key={i.href}>{i.label} <Tech>{i.permission}</Tech></a>)}</nav><p className="notice">{payFa.invariant}</p>{children}</ManagementShell>; }
export function Restricted({permission}:{permission:string}): React.ReactElement { return <section className="panel" role="alert"><h2>۴۰۳ — دسترسی کنترل‌شده</h2><p>برای این عملیات مجوز لازم است.</p><Tech>{permission}</Tech></section>; }
export function SafeError({message='پاسخ نامعتبر یا خطای امن پرداخت'}:{message?:string}): React.ReactElement { return <section className="panel error" role="alert"><h2>{message}</h2><p>جزئیات خام پاسخ، credential، signature و body در مرورگر نمایش داده یا ذخیره نمی‌شود.</p></section>; }
