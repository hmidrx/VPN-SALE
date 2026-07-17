import { CustomerApp } from "../../../src/components/CustomerApp";
export default async function Page({ searchParams }: { searchParams?: Promise<{ ids?: string }> }): Promise<React.ReactElement> { const params = await searchParams; return <CustomerApp page="catalog-compare" compareIds={params?.ids ?? ""} />; }
