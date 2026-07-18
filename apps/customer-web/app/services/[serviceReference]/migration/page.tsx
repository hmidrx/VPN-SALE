import { ServiceMigrationNotice } from "../../../../src/service-migrations/status";

export default function CustomerMigrationPage({ params }: { params: { serviceReference: string } }) {
  return (
    <ServiceMigrationNotice
      status={{
        serviceReference: params.serviceReference,
        status: "NONE",
        expectedImpact: "در حال حاضر مهاجرت قابل مشاهده‌ای برای این سرویس وجود ندارد.",
        configurationRefreshRequired: false,
        deliveryReady: true,
      }}
    />
  );
}
