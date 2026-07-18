import { ManagementShell, StatusBadge, Tech } from "../../../../src/components/ManagementShell";
const rows = [
  ["محیط و نسخه", "CONDITIONALLY_READY", "metadata بدون راز"],
  ["مهاجرت پایگاه‌داده", "NOT_RUN", "deployment lock لازم است"],
  ["پشتیبان‌گیری", "NOT_RUN", "آخرین manifest در محیط واقعی"],
  ["Restore drill", "NOT_RUN", "هدف ایزوله"],
  ["Sanaei 3x-ui", "NOT_RUN", "v3.5.0"],
  ["Alireza x-ui", "NOT_RUN", "v1.11.3"],
  ["PasarGuard", "NOT_RUN", "v4.0.2"],
];
export default function Page(): React.ReactElement {
  return <ManagementShell title="عملیات restore-drills" eyebrow="عملیات و انتشار" required="operations.readiness.read"><section className="panel"><h2>گزارش آمادگی</h2><p>این نما فقط شواهد پاک‌سازی‌شده را نمایش می‌دهد و هیچ endpoint کامل، secret، token یا داده مشتری را نشان نمی‌دهد.</p><table><tbody>{rows.map(([name,status,evidence])=><tr key={name}><th>{name}</th><td><StatusBadge value={status}/></td><td><Tech>{evidence}</Tech></td></tr>)}</tbody></table></section><section className="cards"><a className="panel" href="/management/operations/releases">انتشارها</a><a className="panel" href="/management/operations/backups">پشتیبان‌ها</a><a className="panel" href="/management/operations/restore-drills">تمرین بازیابی</a><a className="panel" href="/management/operations/provider-certification">گواهی provider</a></section></ManagementShell>;
}
