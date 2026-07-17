import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { ConstraintEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش محدودیت‌ها" required="catalog.update"><ConstraintEditor/></CatalogShell>; }
