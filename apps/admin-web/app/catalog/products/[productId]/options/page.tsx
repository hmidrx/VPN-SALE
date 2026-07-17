import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { OptionEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش گزینه‌ها" required="catalog.update"><OptionEditor/></CatalogShell>; }
