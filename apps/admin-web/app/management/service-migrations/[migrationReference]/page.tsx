import { MigrationDashboard } from "../../../../src/service-migrations/console";

export default function ServiceMigrationDetailPage({ params }: { params: { migrationReference: string } }) {
  return (
    <MigrationDashboard
      migrations={[{
        migrationReference: params.migrationReference,
        serviceReference: "SVC-SAFE",
        status: "AWAITING_APPROVAL",
        safeReasonCategory: "MAINTENANCE",
        expectedImpact: "اشتراک پایدار می‌ماند و محتوا پس از cutover تاییدشده تغییر می‌کند.",
        targetLabels: ["مقصد امن"],
        credentialStrategies: ["PRESERVE_SHARED_CREDENTIAL", "ROTATE_PER_ATTACHMENT_CREDENTIAL"],
        highRisk: true,
        rollbackFeasible: true,
      }]}
    />
  );
}
