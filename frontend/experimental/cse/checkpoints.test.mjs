import assert from "node:assert/strict";
import { mkdtemp, realpath, rm } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { authorityJournal } from "./authority-journal.mjs";
import { directoryAuthority, directoryClient, directoryPins, endorseRotation } from "./checkpoints.mjs";
import { sign, signingKey } from "./format.mjs";
import { recipientKey, unwrap } from "./envelopes.mjs";
import { createEnrollment, deviceEntry, fingerprint } from "./trust.mjs";

const id = () => crypto.randomUUID();
function storage() {
  const data = new Map();
  return {
    read: async (key) => structuredClone(data.get(key)),
    async update(key, change, guard) {
      if (guard) assert.deepEqual(data.get(guard.key), guard.expected);
      data.set(key, structuredClone(change(structuredClone(data.get(key)))));
    },
  };
}

async function fixture() {
  const tenant = id();
  const root = await signingKey();
  const device = await signingKey();
  let time = 100_000;
  const now = () => time;
  const authority = directoryAuthority(tenant, root, now);
  const record = await deviceEntry(device.publicKey, {
    tenant, subject: id(), device: id(), purpose: "sign", keyId: id(), status: "active", epoch: 1,
  });
  const first = await authority.publish([record]);
  const pin = await fingerprint(root.publicKey);
  const pins = await directoryPins(tenant, root.publicKey, pin);
  const store = storage();
  const client = (changes = {}) => directoryClient({ tenant, pins, store, latest: authority.latest, now, ...changes });
  const revoke = () => authority.publish([{ ...record, status: "revoked", epoch: 2 }]);
  return { tenant, root, pin, record, device, authority, first, client, revoke, store, now, advance: (ms) => { time += ms; } };
}

test("directory rejects recipient replacement and invalid record signatures", async () => {
  const f = await fixture();
  const receiver = await recipientKey();
  const row = await deviceEntry(receiver.publicKey, { ...f.record, purpose: "receive", keyId: id() });
  await f.authority.publish([f.record, row]);
  const other = await recipientKey();
  const replacement = (await deviceEntry(other.publicKey, row)).publicKey;
  const client = f.client({ latest: async (query) => {
    const view = await f.authority.latest(query);
    view.entries.find((entry) => entry.purpose === "receive").publicKey = replacement;
    return view;
  } });
  await assert.rejects(client.authorize(row), /digest/);
  const badSignature = f.client({ latest: async (query) => {
    const view = await f.authority.latest(query);
    view.entries.find((entry) => entry.purpose === "receive").signature[0] ^= 1;
    return view;
  } });
  await assert.rejects(badSignature.authorize(row), /signature/);
  assert.equal(await f.store.read(f.tenant), undefined);
  assert.equal((await f.client().authorize(row)).entry.keyId, row.keyId);
});

test("authority signing key and first-contact substituted pin are rejected", async () => {
  const f = await fixture();
  const rogue = await signingKey();
  await assert.rejects(directoryPins(f.tenant, rogue.publicKey, f.pin), /fingerprint/);
  const other = directoryAuthority(f.tenant, rogue, f.now);
  await other.publish([f.record]);
  await assert.rejects(f.client({ latest: other.latest }).authorize(f.record), /checkpoint invalid/);
});

test("historical signed checkpoint and active entry cannot be replayed after revoke on first contact or restore", async () => {
  const f = await fixture();
  const reply = await f.authority.latest({ tenant: f.tenant, nonce: "0".repeat(64), after: 0 });
  await f.client().authorize(f.record);
  const oldStore = storage();
  await oldStore.update(f.tenant, () => ({ sequence: 1, digest: reply.proof.head }));
  await f.revoke();
  for (const store of [storage(), oldStore]) {
    await assert.rejects(f.client({ store, latest: async () => reply }).authorize(f.record), /freshness/);
    await assert.rejects(f.client({ store }).authorize(f.record), /revoked/);
    assert.equal((await store.read(f.tenant)).sequence, 2);
  }
});

test("same-sequence witness equivocation preserves last accepted checkpoint", async () => {
  const f = await fixture();
  await f.client().authorize(f.record);
  const saved = await f.store.read(f.tenant);
  const alternate = directoryAuthority(f.tenant, f.root, f.now);
  const next = { ...f.record, keyId: id(), epoch: 2 };
  await alternate.publish([next]);
  await assert.rejects(f.client({ latest: alternate.latest }).authorize(next), /equivocation/);
  assert.deepEqual(await f.store.read(f.tenant), saved);
});

test("witness unavailable, local corruption, future skew and expiration fail closed", async (t) => {
  await t.test("unavailable", async () => {
    const f = await fixture();
    await assert.rejects(f.client({ latest: async () => { throw new Error("Witness unavailable"); } }).authorize(f.record), /unavailable/);
  });
  await t.test("corrupt", async () => {
    const f = await fixture();
    await f.store.update(f.tenant, () => ({ sequence: 8, digest: "invalid" }));
    await assert.rejects(f.client().authorize(f.record), /corrupt/);
    assert.equal((await f.store.read(f.tenant)).digest, "invalid");
  });
  await t.test("clock skew", async () => {
    const f = await fixture();
    await assert.rejects(f.client({ now: () => f.now() - 2_001 }).authorize(f.record), /freshness/);
    await assert.rejects(f.client({ now: () => f.now() + 2_001 }).authorize(f.record), /freshness/);
    await f.client({ now: () => f.now() + 1_000 }).authorize(f.record);
  });
  await t.test("expired proof", async () => {
    const f = await fixture();
    await assert.rejects(f.client({ latest: async (query) => {
      const view = await f.authority.latest(query);
      f.advance(30_000);
      return view;
    } }).authorize(f.record), /freshness/);
    assert.equal(await f.store.read(f.tenant), undefined);
  });
});

test("Tenant and Organization substitution are denied even for the same signing key", async () => {
  const f = await fixture();
  const other = id();
  await assert.rejects(f.client().authorize({ ...f.record, tenant: other }), /scope/);
  const otherAuthority = directoryAuthority(other, f.root, f.now);
  await otherAuthority.publish([{ ...f.record, tenant: other }]);
  await assert.rejects(f.client({ latest: (query) => otherAuthority.latest({ ...query, tenant: other }) })
    .authorize(f.record), /checkpoint/);
});

test("authority rotation requires dual endorsement and linked cutover", async () => {
  const f = await fixture();
  await f.client().authorize(f.record);
  const next = await signingKey();
  const endorsed = await endorseRotation(f.tenant, f.root, next, f.first);
  await assert.rejects(directoryPins(f.tenant, f.root.publicKey, f.pin, [{ ...endorsed, oldSignature: new Uint8Array(64) }]), /endorsement/);
  const pins = await directoryPins(f.tenant, f.root.publicKey, f.pin, [endorsed]);
  await assert.rejects(f.client({ pins }).authorize(f.record), /freshness/);
  await f.authority.publish([f.record], next);
  await assert.rejects(f.client().authorize(f.record), /checkpoint/);
  assert.equal((await f.client({ pins }).authorize(f.record)).head.sequence, 2);
  await f.authority.publish([f.record]);
  await f.authority.publish([f.record]);
  assert.equal((await f.client({ pins }).authorize(f.record)).head.sequence, 4);
});

test("enrollment proof needs a current endorsing signer and remains single-use across clients", async () => {
  const f = await fixture();
  const candidate = await signingKey();
  const receiver = await recipientKey();
  const enrollment = await createEnrollment(f.tenant, f.record.subject, id(), receiver.publicKey, candidate.publicKey, f.now() + 5_000);
  const proof = await unwrap(enrollment.challenge, receiver, enrollment.context);
  const signature = await sign(candidate.privateKey, enrollment.payload);
  const endorsement = await sign(f.device.privateKey, enrollment.payload);
  const approve = () => f.client().approveEnrollment(f.record, enrollment, proof, signature, endorsement);
  try {
    await assert.rejects(f.client().approveEnrollment(f.record,
      { ...enrollment, context: { ...enrollment.context, version: id() } }, proof, signature, endorsement), /scope/);
    await approve();
    await assert.rejects(approve(), /replay/);
    await f.revoke();
    await assert.rejects(approve(), /revoked/);
  } finally {
    proof.fill(0);
  }
});

test("two-tab out-of-order updates and interrupted writes never overwrite newer trust state", async () => {
  const f = await fixture();
  let unblock;
  let observing;
  const unblocked = new Promise((resolve) => { unblock = resolve; });
  const waiting = new Promise((resolve) => { observing = resolve; });
  const delayed = f.client({ latest: async (query) => {
    const response = await f.authority.latest(query);
    observing();
    await unblocked;
    return response;
  } }).authorize(f.record);
  const rejected = assert.rejects(delayed, /rollback/);
  await waiting;
  await f.revoke();
  await assert.rejects(f.client().authorize(f.record), /revoked/);
  unblock();
  await rejected;
  const saved = await f.store.read(f.tenant);
  const store = { read: f.store.read, update: async () => { throw new Error("Interrupted transaction"); } };
  await assert.rejects(f.client({ store }).authorize(f.record), /Interrupted/);
  assert.deepEqual(await f.store.read(f.tenant), saved);
});

test("independent witness reopens its journal with current revocation and rejects concurrent publication", async () => {
  const f = await fixture();
  const tmp = await realpath(os.tmpdir());
  const root = await mkdtemp(path.join(tmp, "bluedrive-witness-"));
  let log;
  let parallel;
  try {
    const filename = path.join(root, "directory.sqlite");
    log = authorityJournal(filename);
    parallel = authorityJournal(filename);
    const writer = directoryAuthority(f.tenant, f.root, f.now, log);
    await writer.publish([f.record]);
    const alternate = directoryAuthority(f.tenant, f.root, f.now, parallel);
    const revoked = [{ ...f.record, status: "revoked", epoch: 2 }];
    const results = await Promise.allSettled([writer.publish(revoked), alternate.publish(revoked)]);
    assert.equal(results.filter(({ status }) => status === "fulfilled").length, 1);
    assert.match(results.find(({ status }) => status === "rejected").reason.message, /Concurrent/);
    log.close();
    log = authorityJournal(filename);
    const restored = directoryAuthority(f.tenant, f.root, f.now, log);
    await assert.rejects(f.client({ latest: restored.latest }).authorize(f.record), /revoked/);
    assert.equal((await f.store.read(f.tenant)).sequence, 2);
    const badKey = directoryAuthority(f.tenant, await signingKey(), f.now, log);
    await assert.rejects(f.client({ latest: badKey.latest }).authorize(f.record), /configured key mismatch/);
  } finally {
    log?.close();
    parallel?.close();
    const owned = await realpath(root);
    assert.equal(path.dirname(owned), tmp);
    assert.ok(path.basename(owned).startsWith("bluedrive-witness-"));
    await rm(owned, { recursive: true, force: true, maxRetries: 4 });
  }
});
