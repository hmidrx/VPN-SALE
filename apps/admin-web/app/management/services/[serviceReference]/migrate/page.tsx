import { MigrationDashboard } from "../../../../../src/service-migrations/console";

export default function ServiceMigratePage({ params }: { params: { serviceReference: string } }) {
  return (
    <MigrationDashboard
      migrations={[{
        migrationReference: "MIG-DRAFT",
        serviceReference: params.serviceReference,
        status: "DRAFT",
        safeReasonCategory: "OPERATOR_REQUEST",
        expectedImpact: "شبیه‌سازی بدون رزرو ظرفیت و بدون تماس provider انجام می‌شود.",
        targetLabels: [],
        credentialStrategies: [],
        highRisk: false,
        rollbackFeasible: true,
      }]}
    />
  );
}
