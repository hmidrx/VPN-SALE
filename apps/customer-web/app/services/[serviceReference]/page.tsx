import { CustomerApp } from "../../../src/components/CustomerApp";
export default async function ServicePage({ params }: { params: Promise<{ serviceReference: string }> }): Promise<React.ReactElement> {
  const { serviceReference } = await params;
  return <CustomerApp page="service-detail" serviceReference={serviceReference} />;
}
