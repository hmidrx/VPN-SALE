import { CustomerApp } from "../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ invoiceReference: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="invoice-detail" invoiceReference={resolved.invoiceReference} />; }
