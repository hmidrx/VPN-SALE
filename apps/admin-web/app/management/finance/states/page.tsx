import { FinanceShell, FinancialState } from '../../../../src/components/FinanceShell';
export default function Page(): React.ReactElement { return <FinanceShell title="وضعیت‌های مالی امن"><FinancialState state="forbidden"/><FinancialState state="unavailable"/><FinancialState state="error"/><FinancialState state="notfound"/></FinanceShell>; }
