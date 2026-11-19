import { accountCsrfHeaders, requestAccountApi } from "@/lib/account-service";
import { bytes, equal, hex, openVerified, random, resumeSealed, seal, sign, verify } from "./format.mjs";
import { importRecipient, publicBytes, unwrap, wrap } from "./envelopes.mjs";
import { createDeviceBundle, deviceSession } from "./device-unlock.mjs";
import { createKit, openKit } from "./recovery.mjs";
import { message } from "./trust.mjs";

let active;
let recovery;
let recoveryConfirmation;
const attempts = new Map();
const notify = (detail) => window.dispatchEvent(new CustomEvent("bluedrive-cse-state", { detail }));
const verifyKey = (raw) => crypto.subtle.importKey("raw", bytes(raw),
  { name: "ECDSA", namedCurve: "P-256" }, false, ["verify"]);
const bundleFrom = (json) => {
  const raw = JSON.parse(json);
  return { ...raw, iv: bytes(raw.iv), sealed: bytes(raw.sealed) };
};

async function verifyDirectory(proof) {
  const pin = process.env.NEXT_PUBLIC_BLUEDRIVE_CSE_FIXTURE_PIN;
  if (!pin || !window.isSecureContext) throw new Error("CSE fixture trust is unavailable.");
  const raw = bytes(proof.payload);
  if (!await verify(await verifyKey(pin), bytes(proof.signature), raw)) throw new Error("Untrusted key directory.");
  const [domain, state] = JSON.parse(new TextDecoder().decode(raw));
  const now = Math.floor(Date.now() / 1000);
  if (domain !== "BlueDrive/development/directory/v1" || !Number.isSafeInteger(state.issued)
      || !Number.isSafeInteger(state.expires) || !(state.issued <= now && now < state.expires)
      || state.expires > state.issued + 4 * 3600) throw new Error("Key directory is stale.");
  return state;
}

export async function directory(workspaceId = null) {
  const { proof, eligible } = await requestAccountApi("/files/api/cse/directory/", { cache: "no-store", workspaceId });
  if (eligible === false) return null;
  return verifyDirectory(proof);
}

export function lockCse() {
  active?.session.logout();
  active = recovery = recoveryConfirmation = undefined;
  attempts.clear();
  notify("Encryption locked");
}

const identityFor = (state, keyId, generation) => ({ tenant: state.tenant, subject: state.subject, keyId, generation });

export async function generateOfflinePackage(isRecovery) {
  const state = await directory();
  const identity = identityFor(state, crypto.randomUUID(), 1);
  const result = await (isRecovery ? createKit(identity) : createDeviceBundle(identity));
  try {
    return {
      bundle: { ...result.bundle, iv: hex(result.bundle.iv), sealed: hex(result.bundle.sealed) },
      material: hex(result.offlineMaterial),
      public: { sign: hex(await publicBytes(result.signerPublic)), receive: hex(await publicBytes(result.receivePublic)) },
    };
  } finally { result.offlineMaterial.fill(0); }
}

export async function unlockCse(bundleJson, material) {
  const bundle = bundleFrom(bundleJson);
  const state = await directory();
  const identity = identityFor(state, bundle.keyId, bundle.generation);
  const requireFreshDevice = async () => {
    const next = await directory();
    const entry = next.devices[identity.keyId];
    if (next.tenant !== identity.tenant || next.subject !== identity.subject || entry?.status !== "active"
        || entry.epoch !== identity.generation || entry.receive !== bundle.receivePublicHex) {
      throw new Error("This device is not approved or has been revoked.");
    }
  };
  if (active) lockCse();
  const session = deviceSession({ bundle, trustedIdentity: identity, requireFreshDevice,
    session: { authenticated: true, ...identity }, idleMs: 300_000 });
  try {
    await session.unlock(async () => bytes(material.trim()));
    const nonce = random(32);
    if (!await verify(await verifyKey(state.devices[identity.keyId].sign), await session.sign(nonce), nonce)) {
      throw new Error("Device key does not match the trusted directory.");
    }
    active = { identity, session };
  } catch (error) {
    session.logout();
    throw error;
  }
  notify("Encryption unlocked");
}

const context = (scope, kind, keyId, epoch) => ({ ...scope, kind, keyId, epoch });
const envelopeBytes = (e) => ({ suite: e.suite, enc: bytes(e.enc), ct: bytes(e.ct) });
const envelopeList = (e) => [e.kind, e.key_id, e.epoch, e.suite, e.enc, e.ct];
const scopeFor = (state, file, version) => ({ tenant: state.tenant, workspace: state.workspace, file, version });
const recoveryCheck = (state) => message("BlueDrive/personal-cse/recovery-check/v1", [
  state.tenant, state.workspace, state.recovery.key_id, state.recovery.generation,
]);

export async function verifyRecoveryKit(bundleJson, material) {
  const state = await directory();
  const identity = identityFor(state, state.recovery.key_id, state.recovery.generation);
  const secret = bytes(material.trim());
  let keys;
  try {
    keys = await openKit(bundleFrom(bundleJson), secret, identity, { authenticated: true, ...identity });
  } finally { secret.fill(0); }
  const approval = await sign(keys.signer, recoveryCheck(state));
  if (!await verify(await verifyKey(state.recovery.sign), approval, recoveryCheck(state))
      || hex(await publicBytes(keys.receive.publicKey)) !== state.recovery.receive) {
    throw new Error("Recovery kit does not match the trusted directory.");
  }
  const contextForKit = context(scopeFor(state, crypto.randomUUID(), crypto.randomUUID()), "personal", identity.keyId, identity.generation);
  const sample = random(32);
  try {
    const envelope = await wrap(sample, keys.receive.publicKey, contextForKit);
    const decoded = await unwrap(envelope, keys.receive, contextForKit);
    const same = equal(sample, decoded);
    decoded.fill(0);
    if (!same) throw new Error("Recovery kit could not read its verification envelope.");
  } finally { sample.fill(0); }
  recoveryConfirmation = hex(approval);
  recovery = { identity, keys };
  notify("Recovery kit verified");
}

function device(state) {
  if (!state || active?.session.status() !== "UNLOCKED") {
    if (active) lockCse();
    throw new Error("Unlock encryption before continuing.");
  }
  const { identity, session } = active;
  const entry = state.devices[identity.keyId];
  if (identity.tenant !== state.tenant || identity.subject !== state.subject
      || entry?.status !== "active" || entry.epoch !== identity.generation) {
    lockCse();
    throw new Error("The device is no longer approved.");
  }
  return { identity, session, entry };
}

function manifestMessage(scope, meta, wireSize, digest) {
  return message("BlueDrive/personal-cse/manifest/v1", [
    scope.tenant, scope.workspace, scope.file, scope.version, meta.logical_size, wireSize, digest, meta.producer, meta.epoch,
    envelopeList(meta.device), envelopeList(meta.recovery),
  ]);
}

async function sealedEnvelope(material, scope, kind, keyId, epoch, raw) {
  const result = await wrap(material, await importRecipient(bytes(raw)), context(scope, kind, keyId, epoch));
  return { kind, key_id: keyId, epoch, suite: result.suite, enc: hex(result.enc), ct: hex(result.ct) };
}

function rewrapMessage(state, scope, digest, envelope) {
  return message("BlueDrive/personal-cse/rewrap/v1", [
    scope.tenant, scope.workspace, scope.file, scope.version, digest, state.recovery.key_id,
    state.recovery.generation, envelopeList(envelope),
  ]);
}

export async function prepareEncryptedUpload(task, file, signal) {
  const state = await directory(task.workspaceId);
  if (!state) throw new Error("This fixture requires independent authorization before encrypting.");
  if (task.destinationId) throw new Error("Encrypted uploads use the root of Personal My Drive.");
  const current = device(state);
  const cached = attempts.get(task.id);
  if (cached?.source === file && cached.scope.workspace === state.workspace && cached.meta.producer === current.identity.keyId) {
    try {
      await resumeSealed(cached.blob, cached.descriptor, cached.scope, cached.producer);
      return cached;
    } catch { attempts.delete(task.id); }
  }
  if (!recoveryConfirmation) throw new Error("Verify your offline recovery kit before uploading.");
  const scope = scopeFor(state, crypto.randomUUID(), crypto.randomUUID());
  const producer = { keyId: current.identity.keyId, publicKey: await verifyKey(current.entry.sign),
    sign: (payload) => current.session.sign(payload) };
  const parts = [];
  notify("Encrypting");
  const { material, descriptor } = await seal(file, scope, producer, (part) => {
    signal.throwIfAborted();
    parts.push(part);
  });
  try {
    const blob = new Blob(parts);
    const meta = {
      format: "cse_v1", file: scope.file, version: scope.version, logical_size: file.size, prefix: hex(parts[0]),
      producer: producer.keyId, epoch: current.entry.epoch, signature: hex(descriptor.signature),
      recovery_proof: recoveryConfirmation,
      device: await sealedEnvelope(material, scope, "device", producer.keyId, current.entry.epoch, current.entry.receive),
      recovery: await sealedEnvelope(material, scope, "personal", state.recovery.key_id, state.recovery.generation, state.recovery.receive),
      manifest_signature: "",
    };
    const digest = hex(descriptor.digest);
    meta.manifest_signature = hex(await current.session.sign(manifestMessage(scope, meta, blob.size, digest)));
    const result = { source: file, blob, scope, meta, digest, descriptor, producer };
    attempts.set(task.id, result);
    notify("Uploading ciphertext");
    return result;
  } finally { material.fill(0); }
}

export function clearEncryptedAttempt(taskId, status = "") {
  attempts.delete(taskId);
  if (status) notify(status);
}

export function markEncryptedVerification() {
  notify("Verifying");
}

export async function downloadCse(fileId, challenge, onProgress) {
  const state = await directory();
  const current = device(state);
  const recipient = current.identity.keyId;
  const signature = hex(await current.session.sign(message("BlueDrive/personal-cse/download/v1", [challenge, recipient])));
  const result = await requestAccountApi(`/files/api/cse/${fileId}/download/`, {
    method: "POST", headers: { ...(await accountCsrfHeaders()), "Content-Type": "application/json" },
    body: JSON.stringify({ challenge, device: recipient, signature }), cache: "no-store",
  });
  const latest = await verifyDirectory(result.proof);
  device(latest);
  const meta = result.metadata;
  const scope = scopeFor(latest, meta.file, meta.version);
  const signer = latest.devices[meta.producer];
  const producer = { keyId: meta.producer, publicKey: await verifyKey(signer.sign) };
  if (latest.tenant !== state.tenant || latest.workspace !== state.workspace || signer.epoch !== meta.epoch
      || !await verify(producer.publicKey, bytes(meta.manifest_signature), manifestMessage(scope, meta, result.wire_size, result.digest))) {
    throw new Error("Encrypted file manifest verification failed.");
  }
  const url = new URL(result.url);
  if (url.origin !== "http://s3.localhost:18339" || url.username || url.password
      || url.searchParams.get("versionId") !== result.provider_version_id) throw new Error("Unexpected ciphertext storage target.");
  notify("Downloading ciphertext");
  const response = await fetch(url, { credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer" });
  if (!response.ok) throw new Error("The encrypted file is unavailable.");
  const blob = await response.blob();
  if (blob.size !== result.wire_size) throw new Error("The encrypted file was incomplete.");
  onProgress({ loaded: blob.size, total: blob.size });
  notify("Decrypting");
  const deviceContext = context(scope, "device", recipient, current.entry.epoch);
  let material;
  let replacement;
  try {
    if (meta.device.key_id === recipient) {
      material = await current.session.unwrap(envelopeBytes(meta.device), deviceContext);
    } else if (result.grant) {
      const { envelope, signature } = result.grant;
      if (envelope.kind !== "device" || envelope.key_id !== recipient || envelope.epoch !== current.entry.epoch
          || !await verify(await verifyKey(latest.recovery.sign), bytes(signature), rewrapMessage(latest, scope, result.digest, envelope))) {
        throw new Error("Recovery grant verification failed.");
      }
      material = await current.session.unwrap(envelopeBytes(envelope), deviceContext);
    } else {
      if (!recovery || recovery.identity.keyId !== meta.recovery.key_id || recovery.identity.generation !== meta.recovery.epoch) {
        notify("Recovery required");
        throw new Error("This device needs the verified offline recovery kit.");
      }
      material = await unwrap(envelopeBytes(meta.recovery), recovery.keys.receive,
        context(scope, "personal", meta.recovery.key_id, meta.recovery.epoch));
      const envelope = await sealedEnvelope(material, scope, "device", recipient, current.entry.epoch, current.entry.receive);
      replacement = { envelope, signature: hex(await sign(recovery.keys.signer, rewrapMessage(latest, scope, result.digest, envelope))) };
    }
    const chunks = [];
    await openVerified(blob, scope, { keyId: producer.keyId, signature: bytes(meta.signature), digest: bytes(result.digest),
      wireLength: result.wire_size }, material, producer, (chunk) => chunks.push(chunk));
    device(await directory());
    if (replacement) {
      await requestAccountApi(`/files/api/cse/${fileId}/rewrap/`, {
        method: "POST", headers: { ...(await accountCsrfHeaders()), "Content-Type": "application/json" },
        body: JSON.stringify({ device: recipient, grant: replacement }),
      });
    }
    const href = URL.createObjectURL(new Blob(chunks, { type: "application/octet-stream" }));
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = result.filename;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(href), 60_000);
    notify("Encrypted file available");
  } catch (error) {
    if (!/offline recovery kit/.test(String(error))) notify("Integrity verification failed");
    throw error;
  } finally { material?.fill(0); }
}
