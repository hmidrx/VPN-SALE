import { CatalogShell } from "../../../../../src/components/CatalogShell"; import { CustomPlanEditor } from "../../../../../src/catalog/editors";
export default function Page(): React.ReactElement { return <CatalogShell title="ویرایش پلن سفارشی" required="catalog.update"><CustomPlanEditor/></CatalogShell>; }
