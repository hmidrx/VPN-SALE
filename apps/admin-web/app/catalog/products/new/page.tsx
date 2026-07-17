import { CatalogShell } from "../../../../src/components/CatalogShell"; import { ProductForm } from "../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ایجاد محصول" required="catalog.create"><ProductForm/><p className="notice">فقط هویت پایدار محصول جمع‌آوری می‌شود؛ provider/server/inbound وجود ندارد.</p></CatalogShell>; }
