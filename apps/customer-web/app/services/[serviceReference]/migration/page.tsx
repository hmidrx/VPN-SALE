import { notFound } from "next/navigation";

import { isOpaqueServiceReference, ServiceMigrationNotice } from "../../../../src/service-migrations/status";

export default async function CustomerMigrationPage({
  params,
}: {
  params: Promise<{ serviceReference: string }>;
}): Promise<React.ReactElement> {
  const { serviceReference } = await params;
  if (!isOpaqueServiceReference(serviceReference)) {
    notFound();
  }
  return (
    <ServiceMigrationNotice
      status={{
        serviceReference,
        status: "NONE",
        expectedImpact: "در حال حاضر مهاجرت قابل مشاهده‌ای برای این سرویس وجود ندارد.",
        configurationRefreshRequired: false,
        deliveryReady: true,
      }}
    />
  );
}
