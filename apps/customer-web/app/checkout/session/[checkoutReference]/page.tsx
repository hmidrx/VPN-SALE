import { CustomerApp } from "../../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ checkoutReference: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="checkout-session" checkoutReference={resolved.checkoutReference} />; }
