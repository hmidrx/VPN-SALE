import { CustomerApp } from "../../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ transactionReference: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="wallet-transaction" transactionReference={resolved.transactionReference} />; }
