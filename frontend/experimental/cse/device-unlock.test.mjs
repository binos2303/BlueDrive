import assert from "node:assert/strict";
import { test } from "node:test";
import { createDeviceBundle, deviceSession } from "./device-unlock.mjs";
import { createKit, openKit } from "./recovery.mjs";
import { fixtureScope, random, utf8, verify } from "./format.mjs";
import { unwrap, wrap } from "./envelopes.mjs";

const id = () => crypto.randomUUID();
const identity = () => ({ tenant: id(), subject: id(), keyId: id(), generation: 1 });

test("encrypted device bundle, with no private key handles, remains locked after reload or copy", async () => {
  const trustedIdentity = identity();
  const session = { ...trustedIdentity, authenticated: true };
  const original = await createDeviceBundle(trustedIdentity);
  const bundle = structuredClone(original.bundle);
  const settings = { bundle, trustedIdentity, session, requireFreshDevice: async () => {} };
  const first = deviceSession(settings);
  const payload = utf8("fixture message");
  assert.deepEqual(Object.keys(bundle).sort(), ["generation", "iv", "keyId", "receivePublicHex", "sealed", "subject", "tenant", "version"]);
  assert.equal(first.status(), "LOCKED");
  await assert.rejects(first.sign(payload), /locked/);
  await assert.rejects(first.unlock(async () => random(32)));
  await assert.rejects(first.unlock(async () => undefined), /cancelled/);
  await assert.rejects(first.unlock(async () => { throw new DOMException("PRF unavailable", "NotSupportedError"); }), { name: "NotSupportedError" });
  const input = original.offlineMaterial.slice();
  await first.unlock(async () => input);
  assert.ok(input.every((value) => value === 0));
  assert.ok(await verify(original.signerPublic, await first.sign(payload), payload));
  first.logout();
  await assert.rejects(first.sign(payload), /locked/);
  await assert.rejects(first.unlock(async () => original.offlineMaterial.slice()), /unavailable/);
  const restarted = deviceSession({ ...settings, bundle: structuredClone(bundle) });
  await assert.rejects(restarted.sign(payload), /locked/);
  await restarted.unlock(async () => original.offlineMaterial.slice());
  restarted.lock();
  assert.equal(restarted.status(), "LOCKED");
  original.offlineMaterial.fill(0);
});

test("revocation, concurrent unlock, logout during unlock and idle timeout fail closed", async () => {
  const trustedIdentity = identity();
  const { bundle, offlineMaterial } = await createDeviceBundle(trustedIdentity);
  const session = { ...trustedIdentity, authenticated: true };
  let revoked = false;
  let time = Date.now();
  const requireFreshDevice = async () => { if (revoked) throw new Error("Device revoked"); };
  const config = { trustedIdentity, bundle, session, idleMs: 50, now: () => time, requireFreshDevice };
  const pending = deviceSession(config);
  let release;
  let started;
  const entering = new Promise((resolve) => { started = resolve; });
  const unlocking = pending.unlock(() => new Promise((resolve) => { release = resolve; started(); }));
  const interrupted = assert.rejects(unlocking, /session ended/);
  await entering;
  await assert.rejects(pending.unlock(async () => offlineMaterial.slice()), /unavailable/);
  pending.logout();
  release(offlineMaterial.slice());
  await interrupted;
  const unlocked = deviceSession(config);
  await unlocked.unlock(async () => offlineMaterial.slice());
  time += 50;
  await assert.rejects(unlocked.sign(utf8("past idle lifetime")), /locked/);
  revoked = true;
  await assert.rejects(unlocked.unlock(async () => offlineMaterial.slice()), /revoked/);
  assert.equal(unlocked.status(), "LOCKED");
  offlineMaterial.fill(0);
});

test("Personal kit preserves export integrity, generation and recovery after restore", async () => {
  const previous = identity();
  const current = { ...previous, generation: 2 };
  const kit1 = await createKit(previous);
  const kit2 = await createKit(current);
  try {
    assert.equal(kit2.offlineMaterial.length, 32);
    assert.notDeepEqual(kit2.offlineMaterial, kit1.offlineMaterial);
    const account = { ...current, authenticated: true, passwordReset: true };
    const restored = structuredClone(kit2.bundle);
    const bad = structuredClone(restored);
    bad.sealed[0] ^= 1;
    await assert.rejects(openKit(bad, kit2.offlineMaterial, current, account));
    await assert.rejects(openKit(kit1.bundle, kit1.offlineMaterial, current, account), /identity/);
    await assert.rejects(openKit(restored, undefined, current, account), /missing/);
    await assert.rejects(openKit(restored, kit1.offlineMaterial, current, account));
    await assert.rejects(openKit(restored, kit2.offlineMaterial, current, { ...account, tenant: id() }), /identity/);
    const context = { ...fixtureScope(), tenant: current.tenant, keyId: current.keyId, epoch: current.generation, kind: "personal" };
    const material = random(32);
    const envelope = await wrap(material, kit2.receivePublic, context);
    const recovered = await openKit(restored, kit2.offlineMaterial, current, { ...account, lastDeviceRevoked: true });
    const plaintext = await unwrap(envelope, recovered.receive, context);
    assert.deepEqual(plaintext, material);
    plaintext.fill(0);
    material.fill(0);
    // Khôi phục đăng ký thiết bị mới với unlock material riêng, không tái sử dụng recovery kit.
    const next = await createDeviceBundle({ ...current, keyId: id() });
    assert.notDeepEqual(next.offlineMaterial, kit2.offlineMaterial);
    await assert.rejects(openKit(next.bundle, next.offlineMaterial, next.bundle, account));
    next.offlineMaterial.fill(0);
  } finally {
    kit1.offlineMaterial.fill(0);
    kit2.offlineMaterial.fill(0);
  }
});
