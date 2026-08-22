import { ManagementShell } from "../../../src/components/ManagementShell";
import { ConfigurationStudio } from "../../../src/configuration/ConfigurationStudio";

export default function ConfigurationCenterPage(): React.ReactElement {
  return <ManagementShell title="هویت و تم محصول" eyebrow="تنظیمات مشترک" required="configuration.read"><ConfigurationStudio /></ManagementShell>;
}
