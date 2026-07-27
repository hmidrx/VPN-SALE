"use client";
import * as React from "react";
import { browserBootstrap, getAuthCapabilities, getProfile, getSessions, passwordLogin, registerPasswordAccount } from "../auth/api-client";
import { CustomerApiError } from "../auth/error-map";
import type { AuthCapabilities } from "../auth/types";

type Mode = "sign-in" | "register";
type Status = { message: string; retryAfter?: number } | null;
const unavailable: AuthCapabilities = { password_login: false, public_registration: false, telegram_login: false, telegram_linking: false, web_credential_enrollment: false, email_recovery: false, telegram_recovery: false, recovery_codes: false };

export function AuthErrorSummary({ status }: { status: Status }): React.ReactElement | null {
  if (!status) return null;
  return <div className="auth-error" role="alert">{status.message}{status.retryAfter ? ` (${status.retryAfter} ثانیه)` : ""}</div>;
}
export function PasswordPolicyHint(): React.ReactElement { return <p className="auth-hint" id="password-policy">رمز عبور باید حداقل ۱۲ نویسه و ترکیبی امن و غیرقابل حدس باشد.</p>; }
function message(error: unknown): Status {
  if (!(error instanceof CustomerApiError)) return { message: "ارتباط با سرویس برقرار نشد. دوباره تلاش کنید." };
  if (error.code === "rate_limited") return { message: "تلاش‌ها بیش از حد مجاز است؛ کمی صبر کنید.", retryAfter: error.retryAfter };
  if (error.code === "registration_conflict") return { message: "ساخت حساب با این اطلاعات ممکن نیست." };
  if (error.code === "validation_failure") return { message: "اطلاعات واردشده با سیاست حساب سازگار نیست." };
  if (error.code === "service_unavailable") return { message: "سرویس موقتاً در دسترس نیست." };
  if (error.code === "feature_unavailable") return { message: "این قابلیت اکنون فعال نیست." };
  return { message: "نام کاربری یا رمز عبور صحیح نیست." };
}
async function finishAuthentication(): Promise<void> { await Promise.all([getProfile(), getSessions()]); window.location.replace("/"); }

export function CustomerSignInForm(): React.ReactElement {
  const [pending, setPending] = React.useState(false); const [status, setStatus] = React.useState<Status>(null);
  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> { event.preventDefault(); if (pending) return; setPending(true); setStatus(null); const data = new FormData(event.currentTarget); try { await passwordLogin(String(data.get("username") ?? ""), String(data.get("password") ?? "")); await finishAuthentication(); } catch (error) { setStatus(message(error)); setPending(false); } }
  return <form className="auth-form" onSubmit={(event) => void submit(event)}><AuthErrorSummary status={status}/><label htmlFor="username">نام کاربری</label><input id="username" name="username" autoComplete="username" required aria-required="true"/><label htmlFor="password">رمز عبور</label><input id="password" name="password" type="password" autoComplete="current-password" required aria-required="true"/><p className="auth-hint">بازیابی رمز عبور در نسخه آینده ارائه می‌شود.</p><button disabled={pending} type="submit">{pending ? "در حال ورود…" : "ورود امن"}</button></form>;
}
export function CustomerRegistrationForm(): React.ReactElement {
  const [pending, setPending] = React.useState(false); const [status, setStatus] = React.useState<Status>(null);
  async function submit(event: React.FormEvent<HTMLFormElement>): Promise<void> { event.preventDefault(); if (pending) return; const data = new FormData(event.currentTarget); const password = String(data.get("password") ?? ""); if (password !== String(data.get("password-confirmation") ?? "")) { setStatus({ message: "تکرار رمز عبور با رمز عبور یکسان نیست." }); return; } setPending(true); setStatus(null); try { await registerPasswordAccount(String(data.get("username") ?? ""), password, String(data.get("email") ?? "") || undefined); await finishAuthentication(); } catch (error) { setStatus(message(error)); setPending(false); } }
  return <form className="auth-form" onSubmit={(event) => void submit(event)}><AuthErrorSummary status={status}/><label htmlFor="username">نام کاربری</label><input id="username" name="username" autoComplete="username" required/><label htmlFor="password">رمز عبور</label><input id="password" name="password" type="password" autoComplete="new-password" aria-describedby="password-policy" required/><PasswordPolicyHint/><label htmlFor="password-confirmation">تکرار رمز عبور</label><input id="password-confirmation" name="password-confirmation" type="password" autoComplete="new-password" required/><label htmlFor="email">ایمیل (اختیاری)</label><input id="email" name="email" type="email" autoComplete="email"/><p className="auth-hint">ایمیل اختیاری است و در این مرحله تأیید یا برای بازیابی استفاده نمی‌شود.</p><button disabled={pending} type="submit">{pending ? "در حال ساخت حساب…" : "ساخت حساب"}</button></form>;
}
export function CustomerAuthLayout({ mode, capabilities }: { mode: Mode; capabilities: AuthCapabilities }): React.ReactElement { const enabled = mode === "sign-in" ? capabilities.password_login : capabilities.public_registration; return <main className="customer auth-page"><section className="auth-card"><header><span className="auth-mark">DR•PING</span><h1>{mode === "sign-in" ? "ورود به حساب" : "ساخت حساب جدید"}</h1><p>دسترسی امن به سرویس‌های شبکه شما</p></header>{enabled ? mode === "sign-in" ? <CustomerSignInForm/> : <CustomerRegistrationForm/> : <div className="auth-error" role="status">این روش احراز هویت اکنون فعال نیست.</div>}{mode === "sign-in" && capabilities.public_registration ? <a href="/auth/register">حساب ندارید؟ ثبت‌نام کنید</a> : null}{mode === "register" && capabilities.password_login ? <a href="/auth/sign-in">قبلاً حساب ساخته‌اید؟ وارد شوید</a> : null}<small>توکن‌ها فقط در حافظه نگهداری می‌شوند؛ نشست ادامه‌دار با کوکی HttpOnly محافظت می‌شود.</small></section></main>; }
export function CustomerAuthController({ mode }: { mode: Mode }): React.ReactElement { const [capabilities, setCapabilities] = React.useState<AuthCapabilities | null>(null); const [failed, setFailed] = React.useState(false); React.useEffect(() => { const controller = new AbortController(); void getAuthCapabilities().then(async (value) => { if (controller.signal.aborted) return; setCapabilities(value); try { await browserBootstrap(); if (!controller.signal.aborted) window.location.replace("/"); } catch (error) { if (!(error instanceof CustomerApiError) || error.status !== 401) setFailed(true); } }).catch(() => setFailed(true)); return () => controller.abort(); }, []); if (failed) return <CustomerAuthLayout mode={mode} capabilities={capabilities ?? unavailable}/>; if (!capabilities) return <main className="customer auth-page"><p role="status">در حال بررسی نشست امن…</p></main>; return <CustomerAuthLayout mode={mode} capabilities={capabilities}/>; }
