import { CustomerApp } from "../../../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ productId: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="catalog-fixed" productId={resolved.productId} />; }
