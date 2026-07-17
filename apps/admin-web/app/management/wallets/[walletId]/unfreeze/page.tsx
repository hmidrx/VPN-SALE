import { FinanceShell } from '../../../../../src/components/FinanceShell'; import { ConfirmBox } from '../../../../../src/components/ManagementShell';
export default function Page(): React.ReactElement { return <FinanceShell title="آزادسازی کیف‌پول" required="wallets.freeze"><section className="panel"><ConfirmBox action="تأیید آزادسازی"/></section></FinanceShell>; }
