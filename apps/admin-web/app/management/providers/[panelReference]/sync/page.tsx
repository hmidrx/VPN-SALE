import React from "react";
import { ManagementShell } from "../../../../../src/components/ManagementShell";
import { ProviderInventoryView } from "../../../../../src/management/providers";
export default async function Page({ params }: { params: Promise<{ panelReference: string }> }): Promise<React.ReactElement> { const { panelReference } = await params; return <ManagementShell title="همگام‌سازی پنل" required="providers.sync"><ProviderInventoryView panelReference={panelReference}/></ManagementShell>; }
