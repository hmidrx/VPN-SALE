import { AuthShell } from "../../../src/components/AuthShell";
export default function StatePage(): React.ReactElement { return <AuthShell eyebrow="وضعیت دسترسی" title="forbidden"><p className="notice">درخواست شما به وضعیت امن جداگانه هدایت شد. لطفاً دوباره وارد شوید یا با مدیر امنیت تماس بگیرید.</p><a className="btn" href="/auth/login">بازگشت به ورود</a></AuthShell>; }
