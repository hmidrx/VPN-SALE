import React from "react";
import { ManagementShell } from "../../../../../src/components/ManagementShell";
import { ProviderCapabilityMatrix } from "../../../../../src/management/providers";
export default async function Page({ params }: { params: Promise<{ panelReference: string }> }): Promise<React.ReactElement> { const { panelReference } = await params; return <ManagementShell title="قابلیت‌های پنل" required="providers.read"><ProviderCapabilityMatrix panelReference={panelReference}/></ManagementShell>; }
