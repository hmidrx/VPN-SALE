"use client";
import { useEffect, useState } from "react";
import { AuthShell } from "../../../src/components/AuthShell";
export default function RecoveryCodesPage(): React.ReactElement { const [codes,setCodes]=useState<string[]>([]); useEffect(()=>{ const raw=sessionStorage.getItem("recovery_display_once"); if(raw){ setCodes(JSON.parse(raw) as string[]); sessionStorage.removeItem("recovery_display_once");}},[]); return <AuthShell eyebrow="یک بار نمایش" title="کدهای بازیابی را ذخیره کنید"><div className="codes">{codes.map((c)=><code className="code" key={c}>{c}</code>)}</div><a className="btn" href="/security/profile">ذخیره کردم</a></AuthShell>; }
