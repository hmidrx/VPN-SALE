import React from "react";
import { ManagementShell } from "../../../../../src/components/ManagementShell";
import { ProviderCapabilityMatrix } from "../../../../../src/management/providers";
export default function Page(): React.ReactElement { return <ManagementShell title="کنسول ارائه‌دهندگان" required="providers.read"><ProviderCapabilityMatrix/></ManagementShell>; }
