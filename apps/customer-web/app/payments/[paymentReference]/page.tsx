import { CustomerApp } from "../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ paymentReference: string }> }): Promise<React.ReactElement> { const { paymentReference } = await params; return <CustomerApp page="payment-detail" paymentReference={paymentReference} />; }
