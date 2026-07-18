import React from "react";
import { ManagementShell } from "../../../../src/components/ManagementShell";
import { ProviderDashboard, ProviderCredentialNotice } from "../../../../src/management/providers";
export default function Page(): React.ReactElement { return <ManagementShell title="کنسول ارائه‌دهندگان" required="providers.read"><ProviderDashboard/><ProviderCredentialNotice/></ManagementShell>; }
