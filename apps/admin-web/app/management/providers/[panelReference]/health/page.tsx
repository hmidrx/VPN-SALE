import React from "react";
import { ManagementShell } from "../../../../../src/components/ManagementShell";
import { ProviderPanelDetail } from "../../../../../src/management/providers";
export default async function Page({ params }: { params: Promise<{ panelReference: string }> }): Promise<React.ReactElement> { const { panelReference } = await params; return <ManagementShell title="سلامت پنل" required="providers.read_diagnostics"><ProviderPanelDetail panelReference={panelReference}/></ManagementShell>; }
