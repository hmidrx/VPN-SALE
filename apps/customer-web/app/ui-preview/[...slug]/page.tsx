import { notFound } from "next/navigation";
import {
  AuthComposition,
  DashboardPreview,
} from "../../../src/components/AuthPreview";
import { CustomerManualTopups } from "../../../src/manual-topups/CustomerManualTopups";
const authScreens = new Set([
  "sign-in",
  "register",
  "forgot-password",
  "recovery-method",
  "recovery-email",
  "recovery-telegram",
  "recovery-code",
  "reset-password",
  "telegram-link",
  "telegram-unlink",
  "devices",
  "admin-totp",
  "admin-recovery-codes",
]);
export default async function Page({
  params,
}: {
  params: Promise<{ slug: string[] }>;
}): Promise<React.ReactElement> {
  if (
    process.env.NODE_ENV === "production" &&
    process.env.NEXT_PUBLIC_IDENTITY_UI_PREVIEW !== "true"
  )
    notFound();
  const { slug } = await params;
  if (slug.length === 1 && slug[0] === "manual-topup")
    return (
      <main className="customer">
        <CustomerManualTopups enabled />
      </main>
    );
  if (
    slug.length === 1 &&
    (slug[0] === "customer" || slug[0] === "reseller" || slug[0] === "admin")
  )
    return <DashboardPreview role={slug[0]} />;
  if (slug.length === 2 && slug[0] === "auth" && authScreens.has(slug[1] ?? ""))
    return <AuthComposition screen={slug[1] ?? ""} />;
  notFound();
}
