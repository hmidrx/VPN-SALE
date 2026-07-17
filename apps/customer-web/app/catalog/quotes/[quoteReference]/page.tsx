import { CustomerApp } from "../../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ quoteReference: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="catalog-quote" quoteReference={resolved.quoteReference} />; }
