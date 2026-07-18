import { notFound } from "next/navigation";

import { MigrationDashboard } from "../../../../src/service-migrations/console";
import { isMigrationReference } from "../../../../src/service-migrations/types";

export default async function ServiceMigrationDetailPage({
  params,
}: {
  params: Promise<{ migrationReference: string }>;
}): Promise<React.ReactElement> {
  const { migrationReference } = await params;
  if (!isMigrationReference(migrationReference)) {
    notFound();
  }
  return (
    <MigrationDashboard
      migrations={[
        {
          migrationReference,
          serviceReference: "SVC-SAFE",
          status: "AWAITING_APPROVAL",
          safeReasonCategory: "MAINTENANCE",
          expectedImpact: "اشتراک پایدار می‌ماند و محتوا پس از cutover تاییدشده تغییر می‌کند.",
          targetLabels: ["مقصد امن"],
          credentialStrategies: ["PRESERVE_SHARED_CREDENTIAL", "ROTATE_PER_ATTACHMENT_CREDENTIAL"],
          highRisk: true,
          rollbackFeasible: true,
        },
      ]}
    />
  );
}
