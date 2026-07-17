import { CatalogShell } from "../../../../src/components/CatalogShell"; import { CategoryForm } from "../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ایجاد دسته" required="catalog.create"><CategoryForm/></CatalogShell>; }
