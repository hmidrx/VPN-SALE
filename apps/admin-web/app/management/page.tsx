import { ManagementShell } from "../../src/components/ManagementShell";
import { OwnerControlDashboard } from "../../src/components/OwnerControlDashboard";

export default function Page(): React.ReactElement {
  return <ManagementShell title="مرکز فرماندهی" eyebrow="مالک سیستم" required="operations.read"><OwnerControlDashboard /></ManagementShell>;
}
