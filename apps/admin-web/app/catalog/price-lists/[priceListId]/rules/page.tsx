import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { PricingRuleEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش قواعد قیمت" required="pricing.manage"><PricingRuleEditor/></CatalogShell>; }
