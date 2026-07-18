import { notFound } from "next/navigation";

import { MigrationDashboard } from "../../../../../src/service-migrations/console";
import { isOpaqueServiceReference } from "../../../../../src/service-migrations/types";

export default async function ServiceMigratePage({
  params,
}: {
  params: Promise<{ serviceReference: string }>;
}): Promise<React.ReactElement> {
  const { serviceReference } = await params;
  if (!isOpaqueServiceReference(serviceReference)) {
    notFound();
  }
  return (
    <MigrationDashboard
      migrations={[
        {
          migrationReference: "MIG-DRAFT",
          serviceReference,
          status: "DRAFT",
          safeReasonCategory: "OPERATOR_REQUEST",
          expectedImpact: "شبیه‌سازی بدون رزرو ظرفیت و بدون تماس provider انجام می‌شود.",
          targetLabels: [],
          credentialStrategies: [],
          highRisk: false,
          rollbackFeasible: true,
        },
      ]}
    />
  );
}
