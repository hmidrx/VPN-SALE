import React from "react";
import { ManagementShell } from "../../../../src/components/ManagementShell";
import { ProviderCredentialNotice } from "../../../../src/management/providers";
export default function Page(): React.ReactElement { return <ManagementShell title="افزودن پنل 3x-ui" required="providers.manage"><ProviderCredentialNotice/></ManagementShell>; }
