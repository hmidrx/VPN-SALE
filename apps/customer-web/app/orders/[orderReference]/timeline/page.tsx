import { CustomerApp } from "../../../../src/components/CustomerApp";
export default async function Page({ params }: { params: Promise<{ orderReference: string }> }): Promise<React.ReactElement> { const resolved = await params; return <CustomerApp page="order-timeline" orderReference={resolved.orderReference} />; }
