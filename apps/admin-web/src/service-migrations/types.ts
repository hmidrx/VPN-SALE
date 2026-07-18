export type MigrationPhase = "source" | "target" | "cutover" | "cleanup" | "rollback";

export interface MigrationSummary {
  migrationReference: string;
  serviceReference: string;
  status: string;
  safeReasonCategory: string;
  expectedImpact: string;
  targetLabels: string[];
  credentialStrategies: string[];
  highRisk: boolean;
  rollbackFeasible: boolean;
}

export interface FailoverProposalSummary {
  proposalReference: string;
  serviceReference: string;
  reason: string;
  sourceUnreachable: boolean;
  requiresStrongerApproval: boolean;
}

export interface OrphanIdentitySummary {
  orphanReference: string;
  migrationReference: string;
  serviceReference: string;
  possibleActive: boolean;
  cleanupApproved: boolean;
}

export function isOpaqueServiceReference(value: string): boolean {
  return /^(SVC|svc)-[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(value);
}

export function isMigrationReference(value: string): boolean {
  return /^(MIG|mig)-[A-Za-z0-9][A-Za-z0-9_-]{2,63}$/.test(value);
}
