import React from "react";
import { ManagementShell } from "../../../../../src/components/ManagementShell";
import { ProviderInventoryView } from "../../../../../src/management/providers";
export default async function Page({ params }: { params: Promise<{ panelReference: string }> }): Promise<React.ReactElement> { const { panelReference } = await params; return <ManagementShell title="موجودی Inbound" required="providers.read_inventory"><ProviderInventoryView panelReference={panelReference}/></ManagementShell>; }
