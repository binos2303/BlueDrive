import { sha256 } from "@noble/hashes/sha2.js";
import { fixtureScope, equal, hex, openVerified, random, resumeSealed, seal, signingKey } from "./format.mjs";
import { recipientKey, unwrap, wrap } from "./envelopes.mjs";
import { DirectoryTrust, deviceEntry, fingerprint, pinAuthority, signEntry } from "./trust.mjs";

const MIB = 1024 * 1024;
const keySlot = "device";
const receiptSlot = "sealed";
const id = () => crypto.randomUUID();
const check = (value, label) => { if (!value) throw new Error(label); };
let unlocked;

async function storage(action, slot, value) {
  if (!globalThis.indexedDB) throw new Error("IndexedDB unavailable");
  const database = await new Promise((resolve, reject) => {
    const request = indexedDB.open("p61-fixture", 1);
    request.onupgradeneeded = () => request.result.createObjectStore("records");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
  try {
    return await new Promise((resolve, reject) => {
      const transaction = database.transaction("records", action === "get" ? "readonly" : "readwrite");
      const store = transaction.objectStore("records");
      const request = action === "put" ? store.put(value, slot) : store[action](slot);
      transaction.oncomplete = () => resolve(request.result);
      transaction.onabort = () => reject(transaction.error);
    });
  } finally {
    database.close();
  }
}

async function deviceStatus() {
  const entry = await storage("get", keySlot);
  if (!entry) return { persisted: false };
  const { recipient, signing, envelope, context, expected } = entry;
  const retrieved = await unwrap(envelope, recipient, context);
  check(equal(expected, sha256(retrieved)), "persisted HPKE key unwrap");
  check(!recipient.privateKey.extractable && !signing.privateKey.extractable, "non-extractable invariant");
  let blocked = false;
  try { await crypto.subtle.exportKey("pkcs8", recipient.privateKey); } catch (error) { blocked = error.name === "InvalidAccessError"; }
  check(blocked, "private key export refused");
  // Cùng origin vẫn có thể dùng key handle lấy từ IndexedDB khi UI fixture đang khóa.
  return { persisted: true, nonExtractable: true, sameOriginUseWhileUiLocked: unlocked === undefined };
}

async function initDevice() {
  const scope = fixtureScope();
  const recipient = await recipientKey();
  const signing = await signingKey();
  const authority = await signingKey();
  const material = random(32);
  const subject = id();
  const device = id();
  const fields = { tenant: scope.tenant, subject, device, keyId: id(), purpose: "receive", epoch: 1, status: "active" };
  const entry = await signEntry(authority.privateKey, await deviceEntry(recipient.publicKey, fields));
  const anchor = await pinAuthority(authority.publicKey, await fingerprint(authority.publicKey));
  const trust = new DirectoryTrust(anchor);
  const publicKey = await trust.accept(entry, fields);
  const revoked = await signEntry(authority.privateKey, { ...entry, status: "revoked", epoch: 2 });
  let denied = false;
  try { await trust.accept(revoked, fields); } catch (error) { denied = /revoked/.test(error.message); }
  check(denied, "signed revocation");
  let rollback = false;
  try { await trust.accept(entry, fields); } catch (error) { rollback = /rollback/.test(error.message); }
  check(rollback, "revocation checkpoint");
  const context = { ...scope, keyId: fields.keyId, kind: "device", epoch: 1 };
  const envelope = await wrap(material, publicKey, context);
  await storage("put", keySlot, { recipient, signing, envelope, context, expected: sha256(material) });
  material.fill(0);
  unlocked = recipient;
  const openWhileUnlocked = await deviceStatus();
  unlocked = undefined;
  return { ...await deviceStatus(), openWhileUnlocked: openWhileUnlocked.persisted, revocation: true, rollback: true };
}

function source(size) {
  const block = new Uint8Array(MIB).fill(0x51);
  return new Blob([...Array.from({ length: Math.floor(size / MIB) }, () => block), block.subarray(0, size % MIB)]);
}

async function probeOpfs() {
  let directory;
  const name = "p61-probe-" + id();
  try {
    if (typeof navigator.storage?.getDirectory !== "function") return { supported: false, reason: "getDirectory unavailable" };
    directory = await navigator.storage.getDirectory();
    const file = await directory.getFileHandle(name, { create: true });
    if (typeof file.createWritable !== "function") return { supported: false, reason: "createWritable unavailable" };
    const writer = await file.createWritable();
    await writer.write(new Uint8Array([0x51]));
    await writer.close();
    check((await file.getFile()).size === 1, "OPFS probe size");
    return { supported: true };
  } catch (error) {
    if (!["UnknownError", "NotSupportedError", "SecurityError"].includes(error.name)) throw error;
    return { supported: false, reason: error.name };
  } finally {
    if (directory) await directory.removeEntry(name).catch(() => {});
  }
}

async function runCase(size, keep, opfs) {
  const input = source(size);
  const scope = fixtureScope();
  const producer = { ...await signingKey(), keyId: id() };
  const directory = opfs ? await navigator.storage.getDirectory() : null;
  const name = "p61-sealed-" + id();
  const fileHandle = directory && await directory.getFileHandle(name, { create: true });
  const writer = opfs ? await fileHandle.createWritable() : null;
  const parts = [];
  let writeMs = 0;
  let readMs = 0;
  let activeBytes = 0;
  let activeBuffers = 0;
  let peakHeap = performance.memory?.usedJSHeapSize ?? null;
  const observe = (bytes, buffers) => {
    activeBytes = Math.max(activeBytes, bytes);
    activeBuffers = Math.max(activeBuffers, buffers);
    if (peakHeap !== null) peakHeap = Math.max(peakHeap, performance.memory.usedJSHeapSize);
  };
  let completed = false;
  try {
    const start = performance.now();
    const sealed = await seal(input, scope, producer, async (part) => {
      const began = performance.now();
      if (writer) await writer.write(part);
      else parts.push(part);
      writeMs += performance.now() - began;
    }, observe);
    if (writer) await writer.close();
    const sealMs = performance.now() - start;
    const readStart = performance.now();
    const blob = writer ? await fileHandle.getFile() : new Blob(parts);
    const getPart = await resumeSealed(blob, sealed.descriptor, scope, producer);
    const first = new Uint8Array(await getPart(1).arrayBuffer());
    check(equal(sha256(first), sha256(new Uint8Array(await getPart(1).arrayBuffer()))), "sealed retry bytes");
    readMs = performance.now() - readStart;
    const openStart = performance.now();
    let exported = 0;
    await openVerified(blob, scope, sealed.descriptor, sealed.material, producer, (part) => {
      check(part.every((byte) => byte === 0x51), "plaintext mismatch");
      exported += part.length;
    }, observe);
    sealed.material.fill(0);
    const verifiedExportMs = performance.now() - openStart;
    check(exported === size, "wrong export size");
    if (keep && writer) await storage("put", receiptSlot, {
      name, descriptor: sealed.descriptor, scope, producer: { publicKey: producer.publicKey, keyId: producer.keyId },
      sample: hex(sha256(first)),
    });
    completed = true;
    const estimate = await navigator.storage?.estimate?.();
    return { size, wireBytes: blob.size, sealMs, verifiedExportMs, writeMs, readMs, activeBytes, activeBuffers, peakHeap,
      spool: writer ? "OPFS" : "IN_MEMORY_CIPHERTEXT_ONLY", observedQuota: estimate?.quota ?? null, observedUsage: estimate?.usage ?? null };
  } finally {
    if (writer && !completed) await writer.abort().catch(() => {});
    if (fileHandle && (!keep || !writer || !completed)) await directory.removeEntry(name);
  }
}

async function resumeAfterNavigation(remove) {
  const receipt = await storage("get", receiptSlot);
  if (!receipt) return false;
  const directory = await navigator.storage.getDirectory();
  const handle = await directory.getFileHandle(receipt.name);
  const getPart = await resumeSealed(await handle.getFile(), receipt.descriptor, receipt.scope, receipt.producer);
  check(hex(sha256(new Uint8Array(await getPart(1).arrayBuffer()))) === receipt.sample, "persistent spool resume");
  if (remove) {
    await directory.removeEntry(receipt.name);
    await storage("delete", receiptSlot);
  }
  return true;
}

async function interrupted() {
  const input = source(2 * MIB);
  const scope = fixtureScope();
  const producer = { ...await signingKey(), keyId: id() };
  const partial = [];
  let receipt;
  try {
    receipt = await seal(input, scope, producer, (part) => {
      if (partial.length === 2) throw new DOMException("Fixture interrupted sink", "QuotaExceededError");
      partial.push(part);
    });
  } catch (error) {
    check(error.name === "QuotaExceededError", "unexpected interruption");
  }
  let refused = false;
  try { await resumeSealed(new Blob(partial), receipt?.descriptor); } catch { refused = true; }
  check(refused, "partial spool must not resume");
  const next = await seal(input, { ...scope, version: id() }, producer, () => {});
  check(next.descriptor.wireLength > new Blob(partial).size, "new intent must seal fully");
  next.material.fill(0);
  return true;
}

function worker() {
  return new Promise((resolve, reject) => {
    const running = new Worker("/bench-worker.mjs", { type: "module" });
    running.onmessage = ({ data }) => { running.terminate(); resolve(data); };
    running.onerror = () => { running.terminate(); reject(new Error("Concurrent crypto worker failed")); };
  });
}

async function workers() {
  const results = await Promise.all([worker(), worker()]);
  check(results.every((value) => value.verified) && results[0].digest !== results[1].digest, "two independent worker ciphertexts");
  return results.map((value) => value.ms);
}

globalThis.p61 = { initDevice, deviceStatus, probeOpfs, runCase, resumeAfterNavigation, interrupted, workers };
