"use client";

import { useEffect, useState, type FormEvent } from "react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import Input from "@/components/ui/Input";

type Operation = "device" | "recovery";

export default function CseFixtureControls() {
  const [eligible, setEligible] = useState(false);
  const [operation, setOperation] = useState<Operation | null>(null);
  const [status, setStatus] = useState("Encryption locked");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!process.env.NEXT_PUBLIC_BLUEDRIVE_CSE_FIXTURE_PIN) return;
    let disposed = false;
    const onState = (event: Event) => {
      if (!disposed) setStatus((event as CustomEvent<string>).detail);
    };
    const lock = () => { void import("@/lib/cse/personal.mjs").then((cse) => cse.lockCse()); };
    window.addEventListener("bluedrive-cse-state", onState);
    window.addEventListener("pagehide", lock);
    return () => {
      disposed = true;
      window.removeEventListener("bluedrive-cse-state", onState);
      window.removeEventListener("pagehide", lock);
      lock();
    };
  }, []);

  useEffect(() => {
    if (!process.env.NEXT_PUBLIC_BLUEDRIVE_CSE_FIXTURE_PIN) return;
    let disposed = false;
    void import("@/lib/cse/personal.mjs").then((cse) => cse.directory()).then((state) => {
      if (!disposed) setEligible(Boolean(state));
    }).catch(() => { if (!disposed) setEligible(false); });
    return () => { disposed = true; };
  }, []);

  if (!eligible) return null;

  async function importBundle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const values = new FormData(form);
    const bundle = values.get("bundle");
    const material = values.get("material");
    setError("");
    setBusy(true);
    try {
      if (!(bundle instanceof File) || bundle.size < 1 || bundle.size > 16_384 || typeof material !== "string") {
        throw new Error("Select the matching offline bundle and enter its unlock material.");
      }
      const cse = await import("@/lib/cse/personal.mjs");
      const selected = operation === "recovery" ? cse.verifyRecoveryKit : cse.unlockCse;
      await selected(await bundle.text(), material);
      setOperation(null);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Encrypted keys could not be opened.");
    } finally {
      form.reset();
      setBusy(false);
    }
  }

  async function generate() {
    setError("");
    setBusy(true);
    try {
      const cse = await import("@/lib/cse/personal.mjs");
      const packet = await cse.generateOfflinePackage(operation === "recovery");
      const link = document.createElement("a");
      link.href = URL.createObjectURL(new Blob([JSON.stringify(packet)], { type: "application/json" }));
      link.download = operation === "recovery" ? "bluedrive-offline-recovery.json" : "bluedrive-offline-device.json";
      link.click();
      const url = link.href;
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setStatus("Offline package created. Fixture operator approval required.");
    } catch {
      setError("The offline package could not be created.");
    } finally { setBusy(false); }
  }

  return (
    <>
      <section aria-label="Personal encryption" className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface p-3">
        <p role="status" className="text-sm text-muted">{status}</p>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="secondary" onClick={() => { setError(""); setOperation("device"); }}>Unlock device</Button>
          <Button size="sm" variant="secondary" onClick={() => { setError(""); setOperation("recovery"); }}>Verify recovery kit</Button>
          <Button size="sm" variant="ghost" onClick={() => { void import("@/lib/cse/personal.mjs").then((cse) => cse.lockCse()); }}>Lock</Button>
        </div>
      </section>
      <Dialog open={operation !== null} title={operation === "recovery" ? "Verify offline recovery kit" : "Unlock required"}
        description="Use the approved encrypted bundle and keep its unlock material offline."
        closeDisabled={busy} onClose={() => setOperation(null)}>
        <form className="grid gap-4" onSubmit={importBundle}>
          <label className="grid gap-2 text-sm">Encrypted bundle<Input name="bundle" type="file" accept=".json" /></label>
          <label className="grid gap-2 text-sm">Unlock material<Input name="material" type="password" autoComplete="off" /></label>
          {error && <p role="alert" className="text-sm text-danger">{error}</p>}
          <div className="flex flex-wrap gap-2">
            <Button type="submit" loading={busy}>{operation === "recovery" ? "Verify kit" : "Unlock"}</Button>
            <Button variant="secondary" disabled={busy} onClick={() => { void generate(); }}>Create offline package</Button>
          </div>
        </form>
      </Dialog>
    </>
  );
}
