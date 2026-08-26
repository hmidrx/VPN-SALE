import React from "react";
import { ManagementShell } from "../../../../src/components/ManagementShell";
import { ProviderCredentialNotice, ProviderPanelDetail } from "../../../../src/management/providers";
export default async function Page({ params }: { params: Promise<{ panelReference: string }> }): Promise<React.ReactElement> { const { panelReference } = await params; return <ManagementShell title="مدیریت پنل" required="providers.read"><ProviderPanelDetail panelReference={panelReference}/><ProviderCredentialNotice panelReference={panelReference}/></ManagementShell>; }
