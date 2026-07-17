"use client";
import React from "react";
import { ManagementShell } from "../../../src/components/ManagementShell";
import { createBulk } from "../../../src/customers/api";
export default function CustomerBulkPage(): React.ReactElement { const [refs,setRefs]=React.useState(""); const [result,setResult]=React.useState(""); return <ManagementShell title="عملیات گروهی مشتریان"><section className="panel"><h2>سازنده عملیات گروهی محدود</h2><p>ابتدا snapshot صریح و dry-run ساخته می‌شود؛ هیچ عملیات «همه مشتریان» بدون مرز وجود ندارد.</p><div className="confirm"><label>مراجع مشتریان (هر خط یک UUID)<textarea value={refs} onChange={e=>setRefs(e.target.value)} /></label><button className="btn" onClick={()=>createBulk(refs.split(/\s+/).filter(Boolean),"review",true).then(r=>setResult(JSON.stringify(r,null,2)))}>Dry run افزودن تگ</button></div>{result && <pre className="notice tech">{result}</pre>}</section></ManagementShell>; }
