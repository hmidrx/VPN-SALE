"use client";

import React from "react";
import {
  getTransaction,
  getWalletPolicy,
  getWalletSummary,
  listCredits,
  listReservations,
  listTransactions,
} from "../wallet/api";
import {
  bucketLabel,
  creditStatusLabel,
  displayDate,
  formatTomanFromRial,
  reservationStatusLabel,
  transactionDirectionLabel,
  transactionTypeLabel,
  walletStatusLabel,
} from "../wallet/format";
import type { CreditLot, Reservation, Transaction, WalletPolicy, WalletSummary } from "../wallet/types";

type WalletPage = "overview" | "transactions" | "transaction" | "credits" | "reservations" | "policy";
type LoadState<T> = { loading: boolean; data?: T; error?: string; refreshedAt?: string };

export function WalletNavigation({ current }: { current: "overview" | "transactions" | "top-up" }): React.ReactElement {
  const items = [
    ["overview", "/wallet", "نمای کلی"],
    ["transactions", "/wallet/transactions", "تراکنش‌ها"],
    ["top-up", "/wallet/top-up", "افزایش موجودی"],
  ] as const;
  return <nav className="wallet-tabs" aria-label="بخش‌های اصلی کیف پول">{items.map(([id, href, label]) => <a key={id} href={href} aria-current={current === id ? "page" : undefined}>{label}</a>)}</nav>;
}

export function WalletShell({ page, transactionReference }: { page: WalletPage; transactionReference?: string }): React.ReactElement {
  return <div className="wallet-page"><WalletNavigation current={page === "transactions" || page === "transaction" ? "transactions" : "overview"} />{page === "transactions" ? <Transactions /> : page === "transaction" && transactionReference ? <TransactionDetail reference={transactionReference} /> : page === "credits" ? <Credits /> : page === "reservations" ? <Reservations /> : page === "policy" ? <Policy /> : <Overview />}</div>;
}

function useLoad<T>(loader: (signal: AbortSignal) => Promise<T>): [LoadState<T>, () => void] {
  const [tick, setTick] = React.useState(0);
  const [state, setState] = React.useState<LoadState<T>>({ loading: true });
  React.useEffect(() => {
    const controller = new AbortController();
    setState((old) => ({ ...old, loading: true, error: undefined }));
    loader(controller.signal).then((data) => {
      if (!controller.signal.aborted) setState({ loading: false, data, refreshedAt: new Date().toISOString() });
    }).catch((error: unknown) => {
      if (!controller.signal.aborted) setState((old) => ({ ...old, loading: false, error: errorCode(error) }));
    });
    return () => controller.abort();
  }, [tick]);
  return [state, () => setTick((value) => value + 1)];
}

function errorCode(error: unknown): string {
  return typeof error === "object" && error !== null && "code" in error && typeof error.code === "string" ? error.code : "WALLET_ERROR";
}

export function TomanAmount({ value, className }: { value: number; className?: string }): React.ReactElement {
  return <span className={className ?? "toman-amount"}>{formatTomanFromRial(value)}</span>;
}

function ErrorState({ code, onRetry }: { code?: string; onRetry: () => void }): React.ReactElement {
  const mismatch = code === "projection_mismatch" || code === "PROJECTION_MISMATCH" || code === "NON_EXACT_TOMAN_AMOUNT";
  const title = mismatch ? "نمایش موجودی موقتاً ممکن نیست" : code === "AUTHENTICATION_REQUIRED" ? "برای مشاهده کیف پول وارد حساب شوید." : "دریافت اطلاعات کیف پول ممکن نشد.";
  return <section className="wallet-state error" role="alert"><h1>{title}</h1>{mismatch ? <p>برای محافظت از اطلاعات مالی، موجودی تا پایان بررسی نمایش داده نمی‌شود.</p> : null}<button onClick={onRetry}>تلاش دوباره</button></section>;
}

function WalletHeader({ refresh, loading }: { refresh: () => void; loading: boolean }): React.ReactElement {
  return <header className="wallet-section-head"><div><p className="eyebrow">نمای کلی</p><h1>حساب شما</h1></div><button className="wallet-refresh" onClick={refresh} disabled={loading} aria-label="به‌روزرسانی کیف پول"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 6v5h-5M4 18v-5h5M6.1 9a7 7 0 0 1 11.5-2.4L20 9M4 15l2.4 2.4A7 7 0 0 0 18 15" /></svg></button></header>;
}

function WalletBalanceHero({ summary }: { summary: WalletSummary }): React.ReactElement {
  return <section className={`wallet-balance-hero status-${summary.status.toLowerCase()}`}><div className="wallet-hero-meta"><span>موجودی قابل استفاده</span><span className="status-pill">{walletStatusLabel(summary.status)}</span></div><TomanAmount className="wallet-balance" value={summary.available_balance_rial} />{summary.reserved_balance_rial > 0 ? <a className="reserved-summary" href="/wallet/reservations">رزروشده: <TomanAmount value={summary.reserved_balance_rial} /></a> : null}<div className="wallet-actions"><a className="button" href="/wallet/top-up">افزایش موجودی</a><a href="/wallet/transactions">تراکنش‌ها</a></div></section>;
}

function Overview(): React.ReactElement {
  const [summary, refresh] = useLoad(getWalletSummary);
  const [transactions] = useLoad((signal) => listTransactions(undefined, signal));
  if (summary.error) return <ErrorState code={summary.error} onRetry={refresh} />;
  if (!summary.data) return <WalletSkeleton />;
  return <main className="wallet-overview"><WalletHeader refresh={refresh} loading={summary.loading} /><WalletBalanceHero summary={summary.data} /><RecentTransactions transactions={transactions.data?.items.slice(0, 3) ?? []} loading={transactions.loading} /><WalletBalanceDetails summary={summary.data} /></main>;
}

function RecentTransactions({ transactions, loading }: { transactions: Transaction[]; loading: boolean }): React.ReactElement {
  return <section className="wallet-recent"><header><h2>تراکنش‌های اخیر</h2>{transactions.length ? <a href="/wallet/transactions">مشاهده همه</a> : null}</header>{loading && !transactions.length ? <TransactionSkeleton /> : transactions.length ? transactions.map((tx) => <WalletTransactionRow key={tx.transaction_reference} tx={tx} />) : <WalletEmptyState title="هنوز تراکنشی ندارید" description="پس از شارژ یا خرید، تراکنش‌ها اینجا نمایش داده می‌شوند." />}</section>;
}

function WalletBalanceDetails({ summary }: { summary: WalletSummary }): React.ReactElement {
  const buckets = summary.buckets.filter((bucket) => bucket.balance_rial > 0);
  return <details className="wallet-details"><summary>جزئیات کیف پول</summary><div className="detail-links"><a href="/wallet/credits">اعتبارها</a><a href="/wallet/reservations">رزروها</a><a href="/wallet/policy">قوانین و محدودیت‌ها</a></div>{summary.posted_balance_rial !== summary.available_balance_rial ? <div className="detail-row"><span>موجودی کل</span><TomanAmount value={summary.posted_balance_rial} /></div> : null}{buckets.map((bucket) => <div className="detail-row" key={bucket.bucket_type}><span>{bucketLabel(bucket.bucket_type)}</span><TomanAmount value={bucket.balance_rial} /></div>)}</details>;
}

function WalletTransactionRow({ tx }: { tx: Transaction }): React.ReactElement {
  const incoming = tx.direction === "INCOMING";
  return <a className="wallet-row transaction-row" href={`/wallet/transactions/${encodeURIComponent(tx.transaction_reference)}`}><span className={`transaction-icon ${incoming ? "incoming" : "outgoing"}`} aria-hidden="true">{incoming ? "+" : "−"}</span><span><b>{transactionTypeLabel(tx.type)}</b><time>{displayDate(tx.occurred_at)}</time></span>{tx.amount_rial == null ? null : <span className={incoming ? "amount-incoming" : "amount-outgoing"} aria-label={`${transactionDirectionLabel(tx.direction)}، ${formatTomanFromRial(tx.amount_rial)}`}><TomanAmount value={tx.amount_rial} /></span>}</a>;
}

function Transactions(): React.ReactElement {
  const [items, setItems] = React.useState<Transaction[]>([]);
  const [cursor, setCursor] = React.useState<string | null>();
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState(false);
  const pending = React.useRef(false);
  const load = React.useCallback(async (reset: boolean) => {
    if (pending.current) return;
    pending.current = true; setLoading(true); setError(false);
    try {
      const page = await listTransactions(reset ? undefined : cursor ?? undefined);
      setItems((old) => reset ? page.items : [...old, ...page.items.filter((next) => !old.some((current) => current.transaction_reference === next.transaction_reference))]);
      setCursor(page.next_cursor);
    } catch { setError(true); } finally { pending.current = false; setLoading(false); }
  }, [cursor]);
  React.useEffect(() => { void load(true); }, []);
  return <main><header className="wallet-section-head"><div><p className="eyebrow">کیف پول</p><h1>تراکنش‌ها</h1></div><button className="wallet-refresh" onClick={() => void load(true)} disabled={loading}>به‌روزرسانی</button></header>{items.length ? <><div className="wallet-filter-tabs" aria-label="فیلتر تراکنش‌ها">{["همه", "واریز", "برداشت", "رزرو", "آزادسازی", "بازگشت"].map((label) => <button key={label}>{label}</button>)}</div>{items.map((tx) => <WalletTransactionRow key={tx.transaction_reference} tx={tx} />)}</> : loading ? <TransactionSkeleton /> : <WalletEmptyState title="هنوز تراکنشی ندارید" description="پس از شارژ یا خرید، تراکنش‌ها اینجا نمایش داده می‌شوند." />}{error ? <p className="danger-text">دریافت موارد بیشتر ممکن نشد؛ تراکنش‌های قبلی حفظ شدند.</p> : null}{cursor ? <button className="wallet-load-more" onClick={() => void load(false)} disabled={loading}>نمایش موارد بیشتر</button> : null}</main>;
}

function TransactionDetail({ reference }: { reference: string }): React.ReactElement {
  const [state, refresh] = useLoad((signal) => getTransaction(reference, signal));
  const [copied, setCopied] = React.useState(false);
  if (state.error) return <ErrorState code={state.error} onRetry={refresh} />;
  if (!state.data) return <TransactionSkeleton />;
  const tx = state.data;
  const shortReference = `${tx.transaction_reference.slice(0, 6)}…${tx.transaction_reference.slice(-4)}`;
  const copy = async () => { await navigator.clipboard?.writeText(tx.transaction_reference); setCopied(true); globalThis.setTimeout(() => setCopied(false), 1800); };
  return <main><header className="wallet-section-head"><div><p className="eyebrow">تراکنش</p><h1>{transactionTypeLabel(tx.type)}</h1></div></header><section className="wallet-detail-card">{tx.amount_rial != null ? <TomanAmount className="wallet-balance" value={tx.amount_rial} /> : null}<Field label="نوع تغییر" value={transactionDirectionLabel(tx.direction)} /><Field label="وضعیت" value="ثبت‌شده" /><Field label="زمان" value={displayDate(tx.occurred_at)} /><div className="field"><span>شماره پیگیری</span><button onClick={() => void copy()}><bdi>{shortReference}</bdi> · کپی</button></div><span className="sr-only" aria-live="polite">{copied ? "کپی شد" : ""}</span></section></main>;
}

function Credits(): React.ReactElement {
  const [state, refresh] = useLoad(listCredits);
  if (state.error) return <ErrorState code={state.error} onRetry={refresh} />;
  return <SecondaryPage title="اعتبارها">{state.loading ? <TransactionSkeleton /> : state.data?.items.length ? state.data.items.map((credit) => <CreditRow key={credit.credit_reference} credit={credit} />) : <WalletEmptyState title="اعتبار تاریخ‌دار ندارید" />}</SecondaryPage>;
}
function CreditRow({ credit }: { credit: CreditLot }): React.ReactElement { return <article className="wallet-row"><b>{bucketLabel(credit.bucket_type)}</b><TomanAmount value={credit.remaining_amount_rial} /><span>{creditStatusLabel(credit.status)}</span><small>صدور: {displayDate(credit.issued_at ?? null)} · انقضا: {displayDate(credit.expires_at)}</small></article>; }
function Reservations(): React.ReactElement { const [state, refresh] = useLoad(listReservations); if (state.error) return <ErrorState code={state.error} onRetry={refresh} />; return <SecondaryPage title="رزروها"><p>مبالغ رزروشده تا پایان عملیات قابل استفاده نیستند.</p>{state.loading ? <TransactionSkeleton /> : state.data?.items.length ? state.data.items.map((reservation) => <ReservationRow key={reservation.reservation_reference} reservation={reservation} />) : <WalletEmptyState title="رزرو فعالی ندارید" />}</SecondaryPage>; }
function ReservationRow({ reservation }: { reservation: Reservation }): React.ReactElement { return <article className="wallet-row"><b>{reservationStatusLabel(reservation.status)}</b><TomanAmount value={reservation.amount_rial} /><small>انقضا: {displayDate(reservation.expires_at)}</small></article>; }
function Policy(): React.ReactElement { const [state, refresh] = useLoad(getWalletPolicy); if (state.error) return <ErrorState code={state.error} onRetry={refresh} />; return <SecondaryPage title="قوانین و محدودیت‌ها">{state.data ? <PolicyRows policy={state.data} /> : <TransactionSkeleton />}</SecondaryPage>; }
function PolicyRows({ policy }: { policy: WalletPolicy }): React.ReactElement { return <section className="wallet-detail-card"><Field label="حداقل شارژ" value={<TomanAmount value={policy.minimum_topup_amount_rial} />} /><Field label="وضعیت شارژ آنلاین" value="فعلاً غیرفعال" /><a href="/support">ارتباط با پشتیبانی</a></section>; }
function SecondaryPage({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement { return <main><header className="wallet-section-head"><div><p className="eyebrow">جزئیات کیف پول</p><h1>{title}</h1></div></header>{children}</main>; }
function Field({ label, value }: { label: string; value: React.ReactNode }): React.ReactElement { return <div className="field"><span>{label}</span><strong>{value}</strong></div>; }
function WalletEmptyState({ title, description }: { title: string; description?: string }): React.ReactElement { return <section className="wallet-empty"><h2>{title}</h2>{description ? <p>{description}</p> : null}</section>; }
function WalletSkeleton(): React.ReactElement { return <div aria-label="در حال دریافت اطلاعات" className="wallet-skeleton"><span /><span /><span /></div>; }
function TransactionSkeleton(): React.ReactElement { return <div aria-label="در حال دریافت تراکنش‌ها" className="transaction-skeleton"><span /><span /><span /></div>; }
