import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { TierEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش پله‌های قیمت" required="pricing.manage"><TierEditor/></CatalogShell>; }
