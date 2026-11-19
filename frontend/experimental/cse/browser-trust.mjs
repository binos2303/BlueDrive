import { browserStore, directoryClient, directoryPins } from "./checkpoints.mjs";
import { createDeviceBundle, deviceSession } from "./device-unlock.mjs";
import { createKit, openKit } from "./recovery.mjs";
import { publicBytes } from "./envelopes.mjs";
import { bytes, hex, random, utf8 } from "./format.mjs";

const dbName = "p615-encrypted-device";
const deviceSlot = "bundle";
const signatureBytes = (row) => ({ ...row, signature: Uint8Array.from(row.signature) });
const check = (value, label) => { if (!value) throw new Error(label); };
async function denied(operation, pattern) {
  try { await operation(); } catch (error) { if (pattern.test(error.message)) return; throw error; }
  throw new Error("Fixture unexpectedly allowed operation");
}

async function trust(initial) {
  const root = await crypto.subtle.importKey("raw", bytes(initial.publicKey),
    { name: "ECDSA", namedCurve: "P-256" }, true, ["verify"]);
  const pins = await directoryPins(initial.identity.tenant, root, initial.pin);
  const store = await browserStore(dbName);
  const client = directoryClient({ tenant: initial.identity.tenant, pins, store, latest: async (query) => {
    const result = await globalThis.p615Witness(query);
    return { checkpoint: signatureBytes(result.checkpoint), proof: signatureBytes(result.proof),
      entries: result.entries.map(signatureBytes), links: result.links.map(signatureBytes) };
  } });
  const expected = { ...initial.identity, device: initial.device, purpose: "sign" };
  return { store, authorize: async () => {
    const result = await client.authorize(expected);
    check(result.entry.epoch === initial.identity.generation, "Device key generation mismatch");
    return result;
  } };
}

async function init(identity) {
  const device = await createDeviceBundle(identity);
  const store = await browserStore(dbName);
  try {
    await store.update(deviceSlot, () => device.bundle);
    return { signer: hex(await publicBytes(device.signerPublic)), material: hex(device.offlineMaterial) };
  } finally {
    store.close();
    device.offlineMaterial.fill(0);
  }
}

async function run(initial, { material, copied = false, extra = false } = {}) {
  const { store, authorize } = await trust(initial);
  try {
    const identity = initial.identity;
    const before = await store.read(identity.tenant);
    const bundle = await store.read(deviceSlot);
    check(bundle?.sealed instanceof Uint8Array && Object.values(bundle).every((value) => !(value instanceof CryptoKey)),
      "LOCKED stored an accessible key handle");
    const device = deviceSession({ bundle, trustedIdentity: identity, session: { ...identity, authenticated: true }, requireFreshDevice: authorize });
    await denied(() => device.sign(utf8("locked fixture")), /locked/);
    check(device.status() === "LOCKED", "profile retained an unlocked session");
    const { head } = await authorize();
    if (extra) {
      await denied(() => device.unlock(async () => undefined), /cancelled/);
      const wrong = random(32);
      let rejected = false;
      try { await device.unlock(async () => wrong); } catch (error) { rejected = error.name === "OperationError"; }
      check(rejected && wrong.every((value) => !value), "Wrong material retained or accepted");
      const kit = await createKit(identity);
      try {
        const recovered = await openKit(structuredClone(kit.bundle), kit.offlineMaterial, identity,
          { ...identity, authenticated: true });
        check(recovered.receive.privateKey.extractable === false, "Restored Personal kit did not import safely");
      } finally {
        kit.offlineMaterial.fill(0);
      }
    }
    let verified = false;
    if (material && !copied) {
      await device.unlock(async () => bytes(material));
      const { publicKey } = await authorize();
      verified = await crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, publicKey,
        await device.sign(utf8("unlocked fixture")), utf8("unlocked fixture"));
      check(verified, "Unlocked browser key operations failed");
      device.logout();
      await denied(() => device.sign(utf8("logged-out fixture")), /locked/);
    }
    let prf = "UNKNOWN";
    if (typeof PublicKeyCredential === "undefined") prf = "API_UNAVAILABLE";
    else if (typeof PublicKeyCredential.getClientCapabilities === "function") {
      try {
        const result = await PublicKeyCredential.getClientCapabilities();
        if (result["extension:prf"] === true) prf = "CLIENT_ADVERTISED";
        if (result["extension:prf"] === false) prf = "CLIENT_UNSUPPORTED";
      } catch { prf = "PROBE_UNAVAILABLE"; }
    }
    return { before: before?.sequence ?? null, head: head.sequence, locked: true, verified, prf };
  } finally {
    store.close();
  }
}

async function observe(initial, deniedReason) {
  const { store, authorize } = await trust(initial);
  try {
    if (deniedReason) await denied(authorize, new RegExp(deniedReason));
    else await authorize();
    return (await store.read(initial.identity.tenant))?.sequence;
  } finally { store.close(); }
}

async function revokedUnlock(initial, material) {
  const { store, authorize } = await trust(initial);
  try {
    const identity = initial.identity;
    const device = deviceSession({ bundle: await store.read(deviceSlot), trustedIdentity: identity,
      session: { ...identity, authenticated: true }, requireFreshDevice: authorize });
    let materialRequested = false;
    await denied(() => device.unlock(async () => { materialRequested = true; return bytes(material); }), /revoked/);
    check(!materialRequested && device.status() === "LOCKED", "Revoked device requested unlock material");
  } finally { store.close(); }
}

async function faults(initial) {
  const { store, authorize } = await trust(initial);
  const tenant = initial.identity.tenant;
  const saved = await store.read(tenant);
  try {
    await new Promise((resolve, reject) => {
      const request = indexedDB.open(dbName, 1);
      request.onerror = () => reject(request.error);
      request.onsuccess = () => {
        const db = request.result;
        const transaction = db.transaction("trust", "readwrite");
        transaction.onabort = () => { db.close(); resolve(); };
        transaction.oncomplete = () => { db.close(); reject(new Error("Interrupted write committed")); };
        const put = transaction.objectStore("trust").put({ sequence: 900, digest: saved.digest }, tenant);
        put.onsuccess = () => transaction.abort();
      };
    });
    check((await store.read(tenant)).sequence === saved.sequence, "Aborted write advanced checkpoint");
    await store.update(tenant, () => ({ ...saved, digest: "invalid" }));
    await denied(authorize, /corrupt/);
    check((await store.read(tenant)).digest === "invalid", "Corrupt checkpoint silently overwritten");
    await store.update(tenant, () => saved);
    return { interrupted: true, corrupt: true };
  } finally { store.close(); }
}

globalThis.p615 = { init, run, observe, faults, revokedUnlock };
