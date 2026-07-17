import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { FulfillmentEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="الزامات ایفای سفارش" required="catalog.update"><FulfillmentEditor/></CatalogShell>; }
