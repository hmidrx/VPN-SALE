"use client";

import React from "react";
import { getInvoice, getOrder } from "../commerce/api";
import { getWalletPolicy, getWalletSummary } from "../wallet/api";
import { formatToman, formatTomanFromRial, parseTomanInput, tomanToExactRial } from "../wallet/format";
import { createOrderPaymentIntent, createWalletTopupIntent, getPaymentIntent, listPaymentIntents, listPaymentMethods } from "../payments/api";
import { statusLabel, purposeLabel } from "../payments/format";
import { PaymentOperationController } from "../payments/idempotency";
import { validateRedirectAction } from "../payments/redirect";
import type { PaymentAction, PaymentIntent, PaymentMethod, PaymentPurpose } from "../payments/types";
import { TomanAmount, WalletNavigation } from "./Wallet";
import { MINIMUM_TOPUP_RIAL, MINIMUM_TOPUP_TOMAN, TOPUP_PRESET_TOMAN } from "../wallet/topup-policy";

type Load<T> = { loading: boolean; data?: T; error?: boolean };
function useLoad<T>(loader: (signal: AbortSignal) => Promise<T>, deps: React.DependencyList = []): [Load<T>, () => void] {
  const [tick, setTick] = React.useState(0);
  const [state, setState] = React.useState<Load<T>>({ loading: true });
  React.useEffect(() => { const controller = new AbortController(); setState((old) => ({ ...old, loading: true, error: false })); loader(controller.signal).then((data) => { if (!controller.signal.aborted) setState({ loading: false, data }); }).catch(() => { if (!controller.signal.aborted) setState((old) => ({ ...old, loading: false, error: true })); }); return () => controller.abort(); }, [tick, ...deps]);
  return [state, () => setTick((value) => value + 1)];
}
function ErrorBox({ onRetry }: { onRetry?: () => void }): React.ReactElement { return <section className="payment-state error" role="alert"><h2>دریافت اطلاعات پرداخت ممکن نشد.</h2>{onRetry ? <button onClick={onRetry}>تلاش دوباره</button> : null}</section>; }
function MethodCards({ purpose, selected, onSelect, onAvailability }: { purpose: PaymentPurpose; selected?: string; onSelect: (method: PaymentMethod) => void; onAvailability?: (available: boolean) => void }): React.ReactElement {
  const [methods, reload] = useLoad((signal) => listPaymentMethods(purpose, signal), [purpose]);
  const visible = methods.data?.filter((method) => method.availability === "AVAILABLE") ?? [];
  React.useEffect(() => onAvailability?.(visible.length > 0), [visible.length, onAvailability]);
  if (methods.error) return <ErrorBox onRetry={reload} />;
  if (methods.loading && !methods.data) return <div className="payment-skeleton">در حال دریافت روش‌های پرداخت…</div>;
  if (!visible.length) return <section className="payment-state warn topup-unavailable" data-testid="topup-unavailable"><h2>پرداخت آنلاین فعال نیست</h2><p>برای راهنمایی با پشتیبانی در ارتباط باشید.</p><a href="/support">ارتباط با پشتیبانی</a></section>;
  return <div className="payment-methods" role="radiogroup" aria-label="روش پرداخت">{visible.map((method) => <button key={method.code} className={`payment-method ${selected === method.code ? "selected" : ""}`} role="radio" aria-checked={selected === method.code} onClick={() => onSelect(method)}><strong>{method.display_name}</strong>{method.description ? <span>{method.description}</span> : null}</button>)}</div>;
}
function RedirectBox({ action }: { action: PaymentAction }): React.ReactElement { const url = validateRedirectAction(action); return <section className="payment-state"><h2>آماده پرداخت</h2><p>برای ادامه، وارد صفحه پرداخت شوید.</p><a className="button" href={url.toString()} rel="noreferrer">ادامه پرداخت</a></section>; }

export function WalletTopupPage(): React.ReactElement {
  const [wallet, reload] = useLoad(async (signal) => ({ summary: await getWalletSummary(signal), policy: await getWalletPolicy(signal) }));
  const [amount, setAmount] = React.useState("");
  const [method, setMethod] = React.useState<PaymentMethod>();
  const [hasMethods, setHasMethods] = React.useState(false);
  const [review, setReview] = React.useState(false);
  const [action, setAction] = React.useState<PaymentAction>();
  const [busy, setBusy] = React.useState(false);
  const operation = React.useRef(new PaymentOperationController()).current;
  if (wallet.error) return <ErrorBox onRetry={reload} />;
  if (!wallet.data) return <div className="payment-skeleton">در حال آماده‌سازی کیف پول…</div>;
  const { summary, policy } = wallet.data;
  let toman: number | null = null;
  let rial: number | null = null;
  try { toman = parseTomanInput(amount); rial = tomanToExactRial(toman); } catch { toman = null; rial = null; }
  const validation = rial === null ? (amount ? "مبلغ واردشده معتبر نیست." : null) : rial < MINIMUM_TOPUP_RIAL ? "حداقل مبلغ شارژ ۱۰۰٬۰۰۰ تومان است." : rial > policy.maximum_topup_amount_rial || (policy.maximum_wallet_balance_rial && summary.available_balance_rial + rial > policy.maximum_wallet_balance_rial) ? "این مبلغ قابل پذیرش نیست." : null;
  const changeAmount = (value: string) => { setAmount(value); setReview(false); setAction(undefined); operation.reset(); };
  const submit = async () => { if (busy || rial === null || !method || validation || !hasMethods) return; setBusy(true); try { setAction(await createWalletTopupIntent(rial, method.code, operation.current())); } finally { setBusy(false); } };
  if (action) return <div className="wallet-page"><WalletNavigation current="top-up" /><RedirectBox action={action} /></div>;
  return <main className="wallet-page topup-page"><WalletNavigation current="top-up" /><header className="topup-header"><p className="eyebrow">افزایش موجودی</p><h1>مبلغ شارژ را انتخاب کنید</h1></header><section className="current-balance"><span>موجودی قابل استفاده</span><TomanAmount value={summary.available_balance_rial} /></section><section className="topup-amount"><label htmlFor="topup-amount">مبلغ شارژ</label><div className="amount-input"><input id="topup-amount" inputMode="numeric" autoComplete="off" value={amount} onChange={(event) => changeAmount(event.currentTarget.value)} aria-describedby="amount-currency amount-limits" /><span id="amount-currency">تومان</span>{amount ? <button type="button" onClick={() => changeAmount("")}>پاک کردن</button> : null}</div><div className="quick-amounts" aria-label="مبلغ‌های پیشنهادی">{TOPUP_PRESET_TOMAN.map((candidate) => <button key={candidate} type="button" aria-pressed={toman === candidate} onClick={() => changeAmount(String(candidate))}>{formatToman(candidate)}</button>)}</div><p id="amount-limits" className="topup-limits">حداقل شارژ: {formatToman(MINIMUM_TOPUP_TOMAN)}</p>{validation ? <p className="danger-text" role="alert">{validation}</p> : null}</section><section className="payment-choice"><h2>روش پرداخت</h2><MethodCards purpose="WALLET_TOPUP" selected={method?.code} onSelect={(selected) => { setMethod(selected); setReview(false); }} onAvailability={setHasMethods} /></section>{hasMethods && method && rial !== null && !validation ? review ? <section className="payment-review"><h2>بازبینی شارژ</h2><p>مبلغ: <TomanAmount value={rial} /></p><p>روش: {method.display_name}</p><p>موجودی پس از تأیید: <TomanAmount value={summary.available_balance_rial + rial} /></p><small>موجودی پس از تأیید نهایی پرداخت تغییر می‌کند.</small><button disabled={busy} onClick={() => void submit()}>{busy ? "در حال ثبت…" : "تأیید و ادامه"}</button></section> : <button className="button topup-review" onClick={() => setReview(true)}>ادامه و بازبینی</button> : null}</main>;
}
function IntentCard({ intent }: { intent: PaymentIntent }): React.ReactElement { return <a className="payment-row" href={`/payments/${encodeURIComponent(intent.reference)}`}><span>{purposeLabel(intent.purpose)}</span>{intent.amount_rial != null ? <TomanAmount value={intent.amount_rial} /> : null}<b>{statusLabel(intent.status)}</b></a>; }
export function PaymentsPage(): React.ReactElement { const [list, reload] = useLoad((signal) => listPaymentIntents(undefined, signal)); if (list.error) return <ErrorBox onRetry={reload} />; return <main className="wallet-page"><h1>پرداخت‌های من</h1><a className="button" href="/wallet/top-up">افزایش موجودی</a>{list.data?.items.length ? list.data.items.map((intent) => <IntentCard key={intent.reference} intent={intent} />) : <section className="payment-state"><h2>هنوز پرداختی ندارید</h2></section>}</main>; }
export function PaymentDetailPage({ reference }: { reference: string }): React.ReactElement { const [detail, reload] = useLoad((signal) => getPaymentIntent(reference, signal), [reference]); if (detail.error) return <ErrorBox onRetry={reload} />; if (!detail.data) return <p>در حال دریافت پرداخت…</p>; const intent = detail.data; return <main className="wallet-page"><h1>جزئیات پرداخت</h1><section className="payment-review"><p>{purposeLabel(intent.purpose)} · {statusLabel(intent.status)}</p>{intent.amount_rial != null ? <TomanAmount value={intent.amount_rial} /> : null}{intent.status === "PROCESSING" || intent.status === "REQUIRES_VERIFICATION" ? <p>وضعیت پرداخت در حال بررسی است.</p> : null}{intent.status === "RECONCILIATION_REQUIRED" ? <p>این پرداخت برای بررسی بیشتر ارسال شده است.</p> : null}<button onClick={reload}>بررسی وضعیت</button></section></main>; }
export function PaymentReturnPage(): React.ReactElement { const params = new URLSearchParams(globalThis.location?.search ?? ""); const reference = params.get("payment_reference") ?? params.get("reference") ?? ""; return <main className="wallet-page"><h1>بازگشت از پرداخت</h1><p>وضعیت پرداخت در حال بررسی است.</p>{reference ? <PaymentDetailPage reference={reference} /> : <ErrorBox />}</main>; }
export function OrderPayPage({ orderReference }: { orderReference: string }): React.ReactElement { const [data, reload] = useLoad(async (signal) => { const order = await getOrder(orderReference, signal); const invoice = order.invoice_reference ? await getInvoice(order.invoice_reference, signal) : undefined; return { order, invoice }; }, [orderReference]); const [method, setMethod] = React.useState<PaymentMethod>(); const [action, setAction] = React.useState<PaymentAction>(); const [busy, setBusy] = React.useState(false); const operation = React.useRef(new PaymentOperationController()).current; if (data.error) return <ErrorBox onRetry={reload} />; if (!data.data) return <p>در حال آماده‌سازی پرداخت…</p>; const { order, invoice } = data.data; const payable = Boolean(invoice && invoice.status === "ISSUED" && order.financial_status !== "PAID" && order.status !== "CANCELLED"); const submit = async () => { if (!method || !payable || busy) return; setBusy(true); try { setAction(await createOrderPaymentIntent(orderReference, method.code, operation.current())); } finally { setBusy(false); } }; if (action) return <RedirectBox action={action} />; return <main className="wallet-page"><h1>پرداخت سفارش</h1>{invoice ? <TomanAmount className="wallet-balance" value={invoice.payable_total_rial} /> : <p>صورتحساب قابل پرداخت یافت نشد.</p>}{payable ? <><MethodCards purpose="ORDER_PAYMENT" selected={method?.code} onSelect={setMethod} /><button disabled={!method || busy} onClick={() => void submit()}>ادامه پرداخت</button></> : null}</main>; }
