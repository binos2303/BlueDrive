"use client";

import { useState } from "react";
import { Save, Settings2, ShieldCheck } from "lucide-react";
import AdminBreadcrumb from "@/components/layout/AdminBreadcrumb";

export default function SettingsPage() {
  const [name, setName] = useState("SecureDrive");
  const [timeout, setTimeoutValue] = useState("30");
  const [maintenance, setMaintenance] = useState(false);
  const [audit, setAudit] = useState(true);
  const [saved, setSaved] = useState(false);
  const toggleClass = (value: boolean) => `relative h-6 w-11 rounded-full transition-colors ${value ? "bg-blue-600" : "bg-slate-300"}`;
  return <><AdminBreadcrumb /><div className="mb-6"><h1 className="text-2xl font-semibold text-slate-900">System settings</h1></div>
    <div className="max-w-3xl space-y-5"><section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><div className="flex items-center gap-3"><span className="rounded-xl bg-blue-50 p-2.5 text-blue-600"><Settings2 size={18} /></span><div><h2 className="text-sm font-semibold text-slate-800">General settings</h2></div></div><div className="mt-6 space-y-5"><label className="block"><span className="text-xs font-medium text-slate-700">System name</span><input value={name} onChange={e => { setName(e.target.value); setSaved(false); }} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" /></label><label className="block"><span className="text-xs font-medium text-slate-700">Session timeout (minutes)</span><input type="number" min="5" max="1440" value={timeout} onChange={e => { setTimeoutValue(e.target.value); setSaved(false); }} className="mt-2 w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100" /></label></div></section>
      <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm sm:p-6"><div className="flex items-center gap-3"><span className="rounded-xl bg-emerald-50 p-2.5 text-emerald-600"><ShieldCheck size={18} /></span><div><h2 className="text-sm font-semibold text-slate-800">Security and operations</h2></div></div>{[{ title: "Audit logging", value: audit, set: setAudit }, { title: "Maintenance mode", value: maintenance, set: setMaintenance }].map(item => <div key={item.title} className="flex items-center justify-between gap-4 border-b border-slate-100 py-5 last:border-0 last:pb-0"><div><p className="text-sm font-medium text-slate-800">{item.title}</p></div><button type="button" role="switch" aria-checked={item.value} onClick={() => { item.set(!item.value); setSaved(false); }} className={toggleClass(item.value)}><span className={`absolute top-1 h-4 w-4 rounded-full bg-white shadow-sm transition-all ${item.value ? "left-6" : "left-1"}`} /></button></div>)}</section>
      <div className="flex flex-wrap items-center gap-3"><button onClick={() => setSaved(true)} className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-blue-700"><Save size={16} /> Save changes</button>{saved && <p role="status" className="text-xs text-amber-700">Saved</p>}</div>
    </div>
  </>;
}
