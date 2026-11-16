"use client";

import { useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import { Database, Plus, RefreshCw } from "lucide-react";
import Button from "@/components/ui/Button";
import Dialog from "@/components/ui/Dialog";
import AdminSegmentTabs from "@/components/admin/AdminSegmentTabs";
import { AccountServiceError } from "@/lib/account-service";
import {
  checkRuntimeStorageChallenge, checkStorageChallenge, connectionPath, storageGet, storageWrite,
  type ConnectionProfile, type ProbeChallenge, type StorageBinding, type StorageCapabilities,
  type StorageCluster, type StorageConnection, type StoragePage, type StorageProbe,
} from "@/lib/storage-control-service";

const input = "mt-1 min-h-11 w-full rounded-xl border border-border-strong bg-surface px-3 py-2 text-sm text-foreground";
const labels: Record<string, string> = { draft: "Not checked", verifying: "Checking", read_verified: "Read check passed", ready: "Verified", failed: "Check failed", disabled: "Disabled", awaiting_browser: "Browser check needed", creating: "Preparing sample", cleaning: "Cleaning sample", cleanup_pending: "Cleanup needed", succeeded: "Verified and cleaned", expired: "Expired" };
const codes: Record<string, string> = {
  tls_validation_failed: "The storage certificate could not be verified. Ask your storage operator to check the certificate and trusted CA.",
  storage_identity_rejected: "Storage rejected the configured identity. Ask your storage operator to check its permissions.",
  storage_unreachable: "Storage did not respond. Check its endpoint and network access, then retry.",
  profile_unavailable: "The approved connection profile is unavailable. Ask your storage operator to check its settings.",
  fixture_cleanup_pending: "The temporary verification sample still needs cleanup. Retry cleanup before starting another check.",
};
function message(error: unknown) { return error instanceof Error ? error.message : "The request could not be completed. Retry the action."; }
function time(value: string | null) { return value ? new Date(value).toLocaleString() : "Not yet"; }

export default function StorageConnections({ tenantId, fallback, hasUnsavedLayout = false, renderTopology }: { tenantId?: string; fallback?: ReactNode; hasUnsavedLayout?: boolean; renderTopology?: (cluster: StorageCluster, capabilities: StorageCapabilities) => ReactNode }) {
  const [section, setSection] = useState<"topology" | "connections">("topology");
  const [findStorage, setFindStorage] = useState(false);
  const [caps, setCaps] = useState<StorageCapabilities | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [clusters, setClusters] = useState<StoragePage<StorageCluster> | null>(null);
  const [profiles, setProfiles] = useState<ConnectionProfile[]>([]);
  const [binding, setBinding] = useState<StorageBinding>({ connection_id: null, generation: 0 });
  const [clusterId, setClusterId] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [connections, setConnections] = useState<{ cluster: string; data: StoragePage<StorageConnection> } | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [probeState, setProbeState] = useState<{ connection: string; probes: StorageProbe[] } | null>(null);
  const [query, setQuery] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [revisionPage, setRevisionPage] = useState(1);
  const [refresh, setRefresh] = useState(0);
  const [busy, setBusy] = useState("");
  const busyRef = useRef(false);
  const alive = useRef(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [form, setForm] = useState<"cluster" | "revision" | null>(null);
  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [profileId, setProfileId] = useState("");
  const [formReason, setFormReason] = useState("");
  const [confirmation, setConfirmation] = useState<"probe" | "runtime_probe" | "bind" | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const registration = useRef<{ payload: string; key: string } | null>(null);
  const canConfigure = caps?.permissions["storage.configure"] === true;
  const showTopology = Boolean(caps?.topology_enabled && renderTopology && section === "topology");
  const rows = connections?.cluster === clusterId ? connections.data.results : [];
  const connection = rows.find((item) => item.id === connectionId) ?? rows[0];
  const probes = probeState && connection && probeState.connection === connection.id ? probeState.probes : [];
  const probe = probes.find((item) => ["creating", "awaiting_browser", "cleaning", "cleanup_pending"].includes(item.state)) ?? probes[0];
  const cluster = clusters?.results.find((item) => item.id === clusterId);
  const reasonValid = reason.trim().length >= 8 && reason.trim().length <= 500;
  const blocked = Boolean(busy || detailLoading || detailError || loadError);

  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    const controller = new AbortController();
    const scope = { tenantId };
    async function load() {
      try {
        const capabilities = await storageGet<StorageCapabilities>(scope, "capabilities/", controller.signal);
        const [list, approved, target] = await Promise.all([
          storageGet<StoragePage<StorageCluster>>(scope, `clusters/?q=${encodeURIComponent(search)}&page=${page}`, controller.signal),
          capabilities.permissions["storage.configure"] ? storageGet<{ profiles: ConnectionProfile[] }>(scope, "profiles/", controller.signal) : Promise.resolve({ profiles: [] }),
          capabilities.permissions["storage.configure"] ? storageGet<{ binding: StorageBinding }>(scope, "binding/", controller.signal) : Promise.resolve({ binding: { connection_id: null, generation: 0 } }),
        ]);
        if (controller.signal.aborted) return;
        setCaps(capabilities); setClusters(list); setProfiles(approved.profiles); setBinding(target.binding);
        setClusterId((current) => list.results.some((item) => item.id === current) ? current : list.results[0]?.id ?? "");
        setLoadError(""); setUnavailable(false);
      } catch (cause) {
        if (controller.signal.aborted) return;
        setLoadError(message(cause));
        setUnavailable(cause instanceof AccountServiceError && cause.status === 404);
      }
    }
    void load();
    return () => controller.abort();
  }, [tenantId, refresh, page, search]);

  useEffect(() => {
    if (!caps || !clusterId) return;
    const controller = new AbortController();
    const scope = { tenantId };
    async function load() {
      setDetailLoading(true);
      try {
        const data = await storageGet<StoragePage<StorageConnection>>(scope, `clusters/${clusterId}/connections/?page=${revisionPage}`, controller.signal);
        if (controller.signal.aborted) return;
        setConnections({ cluster: clusterId, data }); setDetailError("");
      } catch (cause) { if (!controller.signal.aborted) setDetailError(message(cause)); }
      finally { if (!controller.signal.aborted) setDetailLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [tenantId, clusterId, revisionPage, refresh, caps]);

  useEffect(() => {
    if (!connection || !canConfigure) return;
    const controller = new AbortController();
    storageGet<{ probes: StorageProbe[] }>({ tenantId }, connectionPath(connection) + "probe/", controller.signal).then((result) => {
      if (!controller.signal.aborted) setProbeState({ connection: connection.id, probes: result.probes });
    }).catch((cause) => { if (!controller.signal.aborted) setDetailError(message(cause)); });
    return () => controller.abort();
  }, [tenantId, connection, canConfigure, refresh]);

  async function act(label: string, action: () => Promise<string>) {
    if (busyRef.current) return;
    busyRef.current = true; setBusy(label); setError(""); setNotice("");
    try { const result = await action(); if (alive.current) { setNotice(result); setConfirmation(null); setConfirmed(false); } }
    catch (cause) { if (alive.current) setError(message(cause)); }
    finally { busyRef.current = false; if (alive.current) { setBusy(""); setRefresh((value) => value + 1); } }
  }

  async function register(event: FormEvent) {
    event.preventDefault();
    const data = form === "revision" ? { profile_id: profileId, reason: formReason } : { profile_id: profileId, reason: formReason, display_name: name, slug };
    const payload = JSON.stringify({ cluster: form === "revision" ? clusterId : null, data });
    if (registration.current?.payload !== payload) registration.current = { payload, key: crypto.randomUUID() };
    const key = registration.current.key;
    await act("Registering connection", async () => {
      const result = await storageWrite<{ connection: StorageConnection }>({ tenantId }, form === "revision" ? `clusters/${clusterId}/connections/` : "clusters/connect/", data, "POST", key);
      if (alive.current) { setClusterId(result.connection.cluster_id); setConnectionId(result.connection.id); setForm(null); setFormReason(""); }
      return "Connection registered. Run a read check before transferring a verification sample.";
    });
  }

  async function browserCheck(target: StorageConnection, challenge: ProbeChallenge) {
    const result = challenge.probe.mode === "runtime"
      ? await checkRuntimeStorageChallenge(target, challenge)
      : { sha256: await checkStorageChallenge(target, challenge) };
    await storageWrite({ tenantId }, `${connectionPath(target)}probes/${challenge.probe.id}/complete/`, result);
    return challenge.probe.mode === "runtime"
      ? "Runtime S3 transfer verified and temporary objects cleaned. This connection can now be prepared for uploads."
      : "LAB transfer verified and the temporary sample cleaned up. You can prepare this connection for new uploads.";
  }

  if (unavailable && fallback) return fallback;
  if (!caps || unavailable) return <section className="space-y-4"><h1 className="text-2xl font-semibold">{tenantId ? "Organization storage" : "Storage connections"}</h1>{loadError ? <><p role="alert" className="text-sm text-muted">{unavailable ? "Storage connections are not enabled for this account or environment." : loadError}</p><Button variant="secondary" onClick={() => setRefresh((value) => value + 1)}>Retry</Button></> : <p role="status" className="text-sm text-muted">Loading storage access…</p>}</section>;

  return <div className="space-y-5">
    <header className="flex flex-wrap items-start justify-between gap-3"><div><h1 className={`${showTopology ? "text-xl sm:text-2xl" : "text-2xl"} font-semibold tracking-tight`}>{tenantId ? "Organization storage" : caps.topology_enabled ? "Storage manager" : "Storage connections"}</h1><p className={`mt-2 max-w-prose text-sm leading-6 text-muted ${showTopology ? "hidden sm:block" : ""}`}>{showTopology ? "Inspect recorded pools, nodes and disks. Arrange the map without changing infrastructure." : "Connect approved storage, verify access and prepare a destination for new uploads. Existing files keep their original storage connection."}</p></div><Button variant="secondary" size={showTopology ? "sm" : "md"} disabled={Boolean(busy) || hasUnsavedLayout} onClick={() => setRefresh((value) => value + 1)}><RefreshCw size={16} />Refresh</Button></header>
    <p hidden={showTopology} className={showTopology ? "hidden" : "rounded-xl border border-border bg-surface p-4 text-sm leading-6"}>{caps.routing_enabled ? "Routing is enabled. New uploads use the prepared destination." : "Routing is off. Preparing a destination will not move files or change the current upload destination."} <span className="text-muted">Live storage health is not monitored here.</span></p>
    {loadError && <p role="alert" className="text-sm text-danger">{loadError} Refresh before making changes.</p>}
    {notice && <p role="status" className="rounded-xl bg-success-soft p-3 text-sm text-success">{notice}</p>}
    {error && !confirmation && <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{error}</p>}
    <section className={showTopology ? "flex flex-wrap items-end gap-3 rounded-xl border border-border bg-surface p-3" : "overflow-hidden rounded-2xl border border-border bg-surface"}>
      <div className={showTopology ? "contents" : "flex flex-wrap items-center justify-between gap-3 border-b border-border p-4"}><h2 className={showTopology ? "sr-only" : "font-semibold"}>Registered storage</h2>{canConfigure && <Button size="sm" disabled={Boolean(busy) || hasUnsavedLayout} onClick={() => { setSection("connections"); setForm(form === "cluster" ? null : "cluster"); setError(""); }}><Plus size={16} />Connect existing storage</Button>}</div>
      <form className={showTopology ? (findStorage ? "order-3 flex w-full flex-wrap items-end gap-2 border-t border-border pt-3" : "hidden") : "flex flex-wrap items-end gap-2 p-4"} onSubmit={(event) => { event.preventDefault(); if (hasUnsavedLayout) return; setSearch(query); setPage(1); setConnectionId(""); }}><label className="min-w-0 flex-1 text-sm font-medium">Find storage<input className={input} value={query} onChange={(event) => setQuery(event.target.value)} maxLength={100} placeholder="Search by name" /></label><Button type="submit" variant="secondary" disabled={Boolean(busy) || hasUnsavedLayout}>Search</Button></form>
      <div className={showTopology ? "min-w-0 flex-1" : "px-4 pb-4"}><label className="text-sm font-medium">Storage<select className={input} value={clusterId} disabled={Boolean(busy) || hasUnsavedLayout || !clusters?.results.length} onChange={(event) => { setClusterId(event.target.value); setConnectionId(""); setRevisionPage(1); setError(""); setNotice(""); setForm(null); }}>{!clusters?.results.length && <option value="">No registered storage</option>}{clusters?.results.map((item) => <option key={item.id} value={item.id}>{item.display_name}</option>)}</select></label>{clusters && (page > 1 || clusters.has_more) && <div className="mt-3 flex flex-wrap items-center gap-3"><Button size="sm" variant="secondary" disabled={page === 1 || Boolean(busy) || hasUnsavedLayout} onClick={() => setPage(page - 1)}>Previous storage</Button><span className="text-xs text-muted">Page {page} · {clusters.count} results</span><Button size="sm" variant="secondary" disabled={!clusters.has_more || Boolean(busy) || hasUnsavedLayout} onClick={() => setPage(page + 1)}>Next storage</Button></div>}</div>
      {showTopology && <Button size="sm" variant="secondary" disabled={hasUnsavedLayout} onClick={() => setFindStorage(!findStorage)}>{findStorage ? "Close search" : "Find storage"}</Button>}
      {!clusters?.results.length && <p className="px-4 pb-5 text-sm text-muted">{search ? "No storage matches this search." : canConfigure ? "Choose an approved profile to register your first connection." : "No storage has been registered for this scope."}</p>}
    </section>
    {caps.topology_enabled && renderTopology && <fieldset disabled={hasUnsavedLayout || Boolean(busy)} className="min-w-0"><AdminSegmentTabs label="Storage sections" value={section} onChange={setSection} tabs={[{ value: "topology", label: "Topology" }, { value: "connections", label: "Connections" }]} /></fieldset>}
    {hasUnsavedLayout && <p role="status" className="text-sm text-warning">Save or discard the layout before changing storage or opening Connections.</p>}
    {showTopology && cluster && renderTopology?.(cluster, caps)}
    {!showTopology && form && <section className="rounded-2xl border border-border bg-surface p-4 sm:p-5"><h2 className="font-semibold">{form === "revision" ? `New connection revision for ${cluster?.display_name}` : "Register existing storage"}</h2>{profiles.length ? <form className="mt-4 space-y-4" onSubmit={(event) => void register(event)}>
      {form === "cluster" && <div className="grid gap-4 sm:grid-cols-2"><label className="text-sm font-medium">Storage name<input className={input} value={name} onChange={(event) => setName(event.target.value)} required maxLength={200} /></label><div><label className="text-sm font-medium">Storage identifier<input className={input} value={slug} onChange={(event) => setSlug(event.target.value)} required maxLength={100} pattern="[a-z0-9][a-z0-9-]*" aria-describedby="storage-slug-hint" /></label><p id="storage-slug-hint" className="mt-1 text-xs text-muted">Lowercase letters, numbers and hyphens.</p></div></div>}
      <label className="block text-sm font-medium">Approved connection profile<select className={input} value={profileId} required onChange={(event) => setProfileId(event.target.value)}><option value="">Choose a profile</option>{profiles.map((item) => <option key={item.id} value={item.id}>{item.label}{item.lab ? " · LAB" : " · Read only"}</option>)}</select></label>
      {profiles.find((item) => item.id === profileId) && <p className="wrap-anywhere text-xs text-muted">{profiles.find((item) => item.id === profileId)?.endpoint_url}</p>}
      <label className="block text-sm font-medium">Reason for registration<textarea className={input} required minLength={8} maxLength={500} value={formReason} onChange={(event) => setFormReason(event.target.value)} /></label><p className="text-xs leading-5 text-muted">Connection profiles are supplied by your storage operator. Credentials stay on the server. Registration does not provision servers or change bucket policies.</p><div className="flex flex-wrap gap-2"><Button type="submit" loading={busy === "Registering connection"} disabled={Boolean(busy) || formReason.trim().length < 8}>Register connection</Button><Button variant="secondary" disabled={Boolean(busy)} onClick={() => setForm(null)}>Cancel</Button></div>
    </form> : <p className="mt-3 text-sm text-muted">No approved profiles are available. Ask your storage operator to add one for this scope, then refresh.</p>}</section>}
    {!showTopology && cluster && <section className="overflow-hidden rounded-2xl border border-border bg-surface" aria-busy={detailLoading}>
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border p-4"><div className="flex min-w-0 items-center gap-2"><Database size={18} className="shrink-0 text-brand-contrast" /><h2 className="wrap-anywhere font-semibold">{cluster.display_name}</h2></div>{canConfigure && <Button variant="secondary" size="sm" disabled={blocked} onClick={() => { setForm("revision"); setError(""); }}>Add connection revision</Button>}</div>
      {detailError && <p role="alert" className="p-4 text-sm text-danger">{detailError} Refresh to retry.</p>}
      {detailLoading && <p role="status" className="px-4 pt-4 text-sm text-muted">Loading connection details…</p>}
      {!connection && !detailLoading && <p className="p-4 text-sm text-muted">No connection revision registered. Add an approved profile to check this storage.</p>}
      {connection && <div className="space-y-5 p-4 sm:p-5">
        <label className="block text-sm font-medium">Connection revision<select className={input} value={connection.id} disabled={Boolean(busy)} onChange={(event) => { setConnectionId(event.target.value); setError(""); setNotice(""); }}>{rows.map((item) => <option key={item.id} value={item.id}>Revision {item.revision} · {item.profile_id} · {labels[item.state] ?? item.state}</option>)}</select></label>
        {connections && (revisionPage > 1 || connections.data.has_more) && <div className="flex flex-wrap gap-2"><Button variant="secondary" size="sm" disabled={Boolean(busy) || revisionPage === 1} onClick={() => setRevisionPage(revisionPage - 1)}>Previous revisions</Button><Button variant="secondary" size="sm" disabled={Boolean(busy) || !connections.data.has_more} onClick={() => setRevisionPage(revisionPage + 1)}>Next revisions</Button></div>}
        <dl className="grid gap-4 text-sm sm:grid-cols-2"><div><dt className="text-muted">Endpoint</dt><dd className="mt-1 wrap-anywhere">{connection.endpoint_url}</dd></div><div><dt className="text-muted">Browser endpoint</dt><dd className="mt-1 wrap-anywhere">{connection.public_endpoint_url}</dd></div><div><dt className="text-muted">Bucket</dt><dd className="mt-1 wrap-anywhere">{connection.bucket}</dd></div><div><dt className="text-muted">Verification</dt><dd className="mt-1 font-medium">{labels[connection.state] ?? connection.state}</dd></div><div><dt className="text-muted">Last read check</dt><dd className="mt-1">{time(connection.read_verified_at)}</dd></div><div><dt className="text-muted">Transfer verified</dt><dd className="mt-1">{time(connection.verified_at)}</dd></div></dl>
        {connection.last_error_code && <p role="alert" className="rounded-xl bg-warning-soft p-3 text-sm text-warning">{codes[connection.last_error_code] ?? "Verification did not finish. Retry the read check or contact your storage operator."}</p>}
        {canConfigure ? <div className="space-y-3 border-t border-border pt-4"><label className="block text-sm font-medium">Reason for action<textarea className={input} value={reason} onChange={(event) => setReason(event.target.value)} minLength={8} maxLength={500} aria-describedby="storage-reason-hint" /></label><p id="storage-reason-hint" className="text-xs text-muted">Use at least 8 characters. The reason is recorded in the storage audit log.</p><div className="flex flex-wrap gap-2"><Button variant="secondary" disabled={blocked || !reasonValid || ["creating", "awaiting_browser", "cleaning", "cleanup_pending"].includes(probe?.state ?? "")} loading={busy === "Checking read access"} onClick={() => void act("Checking read access", async () => { await storageWrite({ tenantId }, connectionPath(connection) + "verify/", { reason }); return "Read access checked. This does not confirm upload access or live storage health."; })}>Check read access</Button>
          {caps.runtime_probes_enabled && <Button variant="secondary" disabled={blocked || !reasonValid || !["read_verified", "ready", "failed"].includes(connection.state) || !connection.read_verified_at || ["creating", "awaiting_browser", "cleaning", "cleanup_pending"].includes(probe?.state ?? "")} onClick={() => { setConfirmation("runtime_probe"); setConfirmed(false); setError(""); }}>Verify runtime transfer</Button>}
          {caps.lab_probes_enabled && connection.verification_scope === "lab" && <Button variant="secondary" disabled={blocked || !reasonValid || !["read_verified", "ready"].includes(connection.state) || ["creating", "awaiting_browser", "cleaning", "cleanup_pending"].includes(probe?.state ?? "")} onClick={() => { setConfirmation("probe"); setConfirmed(false); setError(""); }}>Verify LAB transfer</Button>}
          <Button disabled={blocked || !reasonValid || connection.state !== "ready" || Boolean(connection.last_error_code) || binding.connection_id === connection.id} onClick={() => { setConfirmation("bind"); setConfirmed(false); setError(""); }}>Prepare for new uploads</Button></div><p className="text-xs leading-5 text-muted">{binding.connection_id === connection.id ? `Prepared destination · generation ${binding.generation}. ${caps.routing_enabled ? "Applies to new uploads." : "Routing remains off."}` : "Preparing this revision changes the default for new uploads only when routing is enabled."}{connection.verification_scope === "read_only" && (caps.runtime_probes_enabled ? " This profile requires a completed runtime transfer check before routing." : " Runtime verification is disabled; this connection is not ready for routing.")}</p></div> : <p className="text-sm text-muted">Your access is read only. Configuration requires an explicit storage permission.</p>}
        {canConfigure && probe && <div className="space-y-3 border-t border-border pt-4"><h3 className="text-sm font-semibold">Latest verification sample</h3><p className="text-sm">{labels[probe.state] ?? probe.state}{probe.expired ? " · Time limit reached" : ""}</p><ul className="grid gap-2 text-xs text-muted sm:grid-cols-2">{Object.entries(probe.checks).map(([key,passed]) => <li key={key}>{({ head_bucket: "Bucket access", versioning: "Bucket versioning", cors: "Browser policy", tls: "HTTPS endpoint", sse_configured: "Encryption configured", server_sha256: "Server checksum", version_pinned: "Object version pinned", sse_response: "Encryption response", browser_sha256: "Browser checksum", cleanup: "Sample cleanup" } as Record<string,string>)[key] ?? key}: {passed ? "Passed" : "Not confirmed"}</li>)}</ul>{probe.cleanup_bucket && <p className="wrap-anywhere text-xs text-muted">Pending temporary bucket: {probe.cleanup_bucket}</p>}
          <div className="flex flex-wrap gap-2">{probe.state === "awaiting_browser" && !probe.expired && <Button variant="secondary" disabled={blocked} onClick={() => void act("Checking browser transfer", async () => browserCheck(connection, await storageGet<ProbeChallenge>({ tenantId }, `${connectionPath(connection)}probes/${probe.id}/?authorization=1`)))}>Retry browser check</Button>}{["creating", "awaiting_browser", "cleanup_pending"].includes(probe.state) && <Button variant="secondary" disabled={blocked} onClick={() => void act("Cleaning sample", async () => { await storageWrite({ tenantId }, `${connectionPath(connection)}probes/${probe.id}/cleanup/`, {}); return "Temporary sample cleanup finished. Refresh verification status before preparing a destination."; })}>Clean up sample</Button>}</div>
        </div>}
      </div>}
    </section>}
    <Dialog open={Boolean(confirmation)} title={confirmation === "probe" ? "Verify transfer in LAB storage" : confirmation === "runtime_probe" ? "Verify runtime storage transfer" : "Prepare upload destination"} closeDisabled={Boolean(busy)} onClose={() => { setConfirmation(null); setError(""); }}>
      <p className="text-sm leading-6">{confirmation === "probe" ? "This creates one new temporary bucket and a 64-byte sample using the approved LAB profile. The browser verifies the sample and the server cleans it up. Your data bucket and its policies stay unchanged." : confirmation === "runtime_probe" ? "This checks a 64-byte server sample and a 64-byte browser multipart upload inside the approved existing data bucket. It verifies SHA-256, object version, ETag and cleanup. The application does not create or modify bucket policy." : `Prepare revision ${connection?.revision} of ${cluster?.display_name} as the default destination. Existing files and uploads keep their original connection. ${caps.routing_enabled ? "New uploads will use this destination." : "Routing is off, so the current upload destination stays in use."}`}</p>
      <label className="mt-4 flex min-h-11 items-start gap-3 text-sm"><input type="checkbox" className="mt-1 h-5 w-5 shrink-0 accent-brand-contrast" checked={confirmed} disabled={Boolean(busy)} onChange={(event) => setConfirmed(event.target.checked)} /><span>{confirmation === "probe" ? "I confirm this profile is approved for temporary LAB verification." : confirmation === "runtime_probe" ? "I approve temporary runtime verification objects in the configured application bucket." : "I have reviewed this connection and the effect on new uploads."}</span></label>
      {error && <p role="alert" className="mt-3 text-sm text-danger">{error} You can close this dialog and refresh to recover a pending sample.</p>}
      <div className="mt-5 flex flex-wrap justify-end gap-2"><Button variant="secondary" disabled={Boolean(busy)} onClick={() => setConfirmation(null)}>Cancel</Button><Button disabled={!confirmed || Boolean(busy) || !connection || !reasonValid} loading={Boolean(busy)} onClick={() => {
        if (!connection) return;
        if (confirmation === "probe") void act("Verifying LAB transfer", async () => browserCheck(connection, await storageWrite<ProbeChallenge>({ tenantId }, connectionPath(connection) + "probe/", { reason, confirm_lab_fixture: true })));
        else if (confirmation === "runtime_probe") void act("Verifying runtime transfer", async () => browserCheck(connection, await storageWrite<ProbeChallenge>({ tenantId }, connectionPath(connection) + "probe/", { mode: "runtime", reason, confirm_runtime_fixture: true })));
        else void act("Preparing destination", async () => { await storageWrite({ tenantId }, "binding/", { connection_id: connection.id, expected_generation: binding.generation, reason }, "PATCH"); return caps.routing_enabled ? "Destination prepared for new uploads. Existing files stay in their original storage." : "Destination prepared. Routing remains off; the current upload destination is unchanged."; });
      }}>{(confirmation === "probe" || confirmation === "runtime_probe") ? "Verify and clean up" : "Prepare destination"}</Button></div>
    </Dialog>
  </div>;
}
