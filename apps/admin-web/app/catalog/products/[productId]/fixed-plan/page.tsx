import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { FixedPlanEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش پلن ثابت" required="catalog.update"><FixedPlanEditor/></CatalogShell>; }
