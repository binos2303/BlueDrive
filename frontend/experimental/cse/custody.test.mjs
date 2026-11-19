import assert from "node:assert/strict";
import { fork } from "node:child_process";
import { once } from "node:events";
import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";
import { test } from "node:test";
import { fileURLToPath } from "node:url";
import { approveRequest, envelopeDigest, signRequest } from "./custody-protocol.mjs";
import { importRecipient, publicBytes, recipientKey, unwrap, wrap } from "./envelopes.mjs";
import { fixtureScope, hex, random, signingKey } from "./format.mjs";
import { fingerprint } from "./trust.mjs";

const id = () => crypto.randomUUID();
const worker = fileURLToPath(new URL("./custody-worker.mjs", import.meta.url));

async function fixture(t, { revoked = false } = {}) {
  const tmp = await realpath(os.tmpdir());
  const root = await mkdtemp(path.join(tmp, "bluedrive-custody-"));
  const children = new Set();
  t.after(async () => {
    for (const child of children) {
      child.kill();
      await once(child, "exit");
    }
    const owned = await realpath(root);
    assert.equal(path.dirname(owned), tmp);
    assert.ok(path.basename(owned).startsWith("bluedrive-custody-"));
    await rm(owned, { recursive: true, force: true, maxRetries: 4 });
  });
  const config = path.join(root, "policy.json");
  const database = path.join(root, "authority.sqlite");
  const scope = fixtureScope();
  const requester = { id: id(), ...await signingKey() };
  const recipient = { id: id(), keyId: id(), ...await recipientKey() };
  const custodians = await Promise.all(Array.from({ length: 3 }, async () => ({ id: id(), ...await signingKey() })));
  const row = async (record) => ({ id: record.id, publicKey: hex(await publicBytes(record.publicKey)) });
  const recipientRaw = await publicBytes(recipient.publicKey);
  const recipientFingerprint = await fingerprint(recipient.publicKey);
  await writeFile(config, JSON.stringify({
    tenant: scope.tenant,
    requesters: [{ ...await row(requester), workspaces: [scope.workspace] }],
    recipients: [{ ...await row(recipient), keyId: recipient.keyId }],
    custodians: await Promise.all(custodians.map(async (record, index) => ({ ...await row(record), revoked: revoked && index === 2 }))),
  }), { mode: 0o600 });

  async function start(mode = "serve", fault = "", ledger = database) {
    const env = process.platform === "win32" ? { SystemRoot: process.env.SystemRoot } : {};
    const child = fork(worker, [mode, config, ledger, fault], { env, execArgv: [], serialization: "advanced",
      stdio: ["ignore", "ignore", "ignore", "ipc"] });
    children.add(child);
    const exit = once(child, "exit");
    const waiting = new Map();
    let sequence = 0;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { child.kill(); reject(new Error("Authority fixture timeout")); }, 10_000);
      child.once("error", reject);
      child.on("exit", () => {
        clearTimeout(timer);
        children.delete(child);
        reject(new Error("Authority unavailable"));
        for (const { reject: rejectCall } of waiting.values()) rejectCall(new Error("Authority unavailable"));
      });
      child.on("message", (message) => {
        if (message.kind === "ready") {
          clearTimeout(timer);
          resolve({
            keyId: message.keyId, epoch: message.epoch, publicRaw: message.publicRaw,
            recover(input) { return send("recover", input); },
            unsupported() { return send("export", {}); },
            async stop() { if (child.connected) child.disconnect(); await exit; },
            exit,
          });
          return;
        }
        const call = waiting.get(message.id);
        waiting.delete(message.id);
        if (message.error) call.reject(new Error(message.error));
        else call.resolve(message.result);
      });
    });
    function send(kind, input) {
      if (!child.connected) return Promise.reject(new Error("Authority unavailable"));
      return new Promise((resolve, reject) => {
        const key = ++sequence;
        const timer = setTimeout(() => { waiting.delete(key); reject(new Error("Authority response timeout")); }, 10_000);
        waiting.set(key, {
          resolve(result) { clearTimeout(timer); resolve(result); },
          reject(error) { clearTimeout(timer); reject(error); },
        });
        child.send({ kind, id: key, input }, (error) => {
          if (error && waiting.has(key)) { waiting.get(key).reject(error); waiting.delete(key); }
        });
      });
    }
  }

  async function request(authority, { changes = {}, approvals = [0, 1], source = scope } = {}) {
    const material = random(32);
    t.after(() => material.fill(0));
    const context = { ...source, kind: "organization", keyId: authority.keyId, epoch: authority.epoch };
    const envelope = await wrap(material, await importRecipient(authority.publicRaw), context);
    const ticket = { ...source, caseId: id(), nonce: hex(random(32)), requester: requester.id, recipient: recipient.id,
      recipientKeyId: recipient.keyId, recipientFingerprint, keyId: authority.keyId, epoch: authority.epoch,
      expires: Date.now() + 120_000, reason: "isolated custody fixture", envelopeDigest: envelopeDigest(envelope), ...changes };
    const input = { ticket, requestSignature: await signRequest(ticket, requester.privateKey), recipientRaw, envelope,
      approvals: await Promise.all(approvals.map((index) => approveRequest(ticket, custodians[index].id, custodians[index].privateKey))) };
    return { material, input, context: { ...source, kind: "device", keyId: recipient.keyId, epoch: authority.epoch } };
  }

  function examine(callback, ledger = database) {
    const db = new DatabaseSync(ledger);
    try { return callback(db); } finally { db.close(); }
  }
  const counts = (ledger) => examine((db) => ["cases", "outbox"].map((table) =>
    db.prepare("SELECT COUNT(*) AS count FROM " + table).get().count), ledger);
  const assertRewrap = async (result, entry) => {
    assert.deepEqual(Object.keys(result).sort(), ["ct", "enc", "suite"]);
    const plaintext = await unwrap(result, recipient, entry.context);
    try { assert.deepEqual(plaintext, entry.material); } finally { plaintext.fill(0); }
  };
  return { scope, custodians, requester, start, request, counts, examine, assertRewrap, root };
}

test("independent Organization custody requires signed request, registered recipient and 2-of-3 approvals", async (t) => {
  const f = await fixture(t);
  const service = await f.start("init");
  for (const approvals of [[], [0], [0, 0]]) {
    const entry = await f.request(service, { approvals });
    await assert.rejects(service.recover(entry.input), /denied/);
  }
  const testCases = [
    { requester: f.custodians[0].id }, { recipient: f.custodians[0].id }, { recipientFingerprint: "0".repeat(64) },
    { requester: id() }, { tenant: id() }, { workspace: id() }, { expires: Date.now() - 1 }, { recipientKeyId: id() },
  ];
  for (const changes of testCases) await assert.rejects(service.recover((await f.request(service, { changes })).input), /denied/);
  const entry = await f.request(service);
  await assert.rejects(service.recover({ ...entry.input, requestSignature: random(64) }), /denied/);
  const otherKey = await recipientKey();
  await assert.rejects(service.recover({ ...entry.input, recipientRaw: await publicBytes(otherKey.publicKey) }), /denied/);
  await assert.rejects(service.unsupported(), /Unsupported/);
  assert.deepEqual(f.counts(), [0, 0]);
  await f.assertRewrap(await service.recover(entry.input), entry);
  const complete = await f.request(service, { approvals: [0, 1, 2], source: { ...f.scope, version: id() } });
  await f.assertRewrap(await service.recover(complete.input), complete);
  assert.deepEqual(f.counts(), [2, 2]);
  const audit = f.examine((db) => db.prepare("SELECT tenant, epoch, approvals FROM outbox WHERE case_id=?").get(entry.input.ticket.caseId));
  assert.equal(audit.tenant, f.scope.tenant);
  assert.equal(audit.epoch, service.epoch);
  assert.deepEqual(JSON.parse(audit.approvals), f.custodians.slice(0, 2).map(({ id }) => id).sort());
  await service.stop();
});

test("revoked custodian and forged Platform role cannot authorize recovery", async (t) => {
  const f = await fixture(t, { revoked: true });
  const service = await f.start("init");
  const revoked = await f.request(service, { approvals: [0, 2] });
  await assert.rejects(service.recover(revoked.input), /denied/);
  const entry = await f.request(service, { changes: { requester: id() } });
  entry.input.ticket.platformAdmin = true;
  await assert.rejects(service.recover(entry.input), /denied/);
  assert.deepEqual(f.counts(), [0, 0]);
  await service.stop();
});

test("concurrent approvals and relays produce one receipt and one audit; altered case, nonce and version are denied", async (t) => {
  const f = await fixture(t);
  const first = await f.start("init");
  const second = await f.start();
  const entry = await f.request(first);
  const opposite = { ...entry.input, approvals: [...entry.input.approvals].reverse() };
  const results = await Promise.all([first.recover(entry.input), second.recover(opposite)]);
  assert.deepEqual(results[0], results[1]);
  await f.assertRewrap(results[0], entry);
  const candidates = [
    { changes: { caseId: entry.input.ticket.caseId }, source: { ...f.scope, version: id() } },
    { changes: { nonce: entry.input.ticket.nonce }, source: { ...f.scope, version: id() } },
    {},
  ];
  for (const candidate of candidates) await assert.rejects(second.recover((await f.request(first, candidate)).input), /denied/);
  assert.deepEqual(f.counts(), [1, 1]);
  await first.stop();
  await second.stop();
});

for (const fault of ["before-unwrap", "after-unwrap", "after-rewrap", "after-commit"]) {
  test("authority process crash " + fault + " is recoverable with the identical ticket", async (t) => {
    const f = await fixture(t);
    const failed = await f.start("init", fault);
    const entry = await f.request(failed);
    await assert.rejects(failed.recover(entry.input), /unavailable/);
    assert.equal((await failed.exit)[0], 97);
    const expected = fault === "after-commit" ? 1 : 0;
    assert.deepEqual(f.counts(), [expected, expected]);
    const recovered = await f.start();
    const result = await recovered.recover(entry.input);
    await f.assertRewrap(result, entry);
    assert.deepEqual(await recovered.recover(entry.input), result);
    assert.deepEqual(f.counts(), [1, 1]);
    await recovered.stop();
  });
}

test("audit insert failure rolls back receipt; post-commit backup and restore preserve idempotency and custody", async (t) => {
  const f = await fixture(t);
  const service = await f.start("init");
  const entry = await f.request(service);
  f.examine((db) => db.exec("CREATE TRIGGER refuse_audit BEFORE INSERT ON outbox BEGIN SELECT RAISE(ABORT, 'fixture'); END"));
  await assert.rejects(service.recover(entry.input), /denied/);
  assert.deepEqual(f.counts(), [0, 0]);
  f.examine((db) => db.exec("DROP TRIGGER refuse_audit"));
  const result = await service.recover(entry.input);
  await service.stop();
  const backup = path.join(f.root, "restored.sqlite");
  f.examine((db) => db.prepare("VACUUM INTO ?").run(backup));
  const restored = await f.start("serve", "", backup);
  assert.deepEqual(await restored.recover(entry.input), result);
  await f.assertRewrap(await restored.recover(entry.input), entry);
  await assert.rejects(restored.recover((await f.request(restored)).input), /denied/);
  assert.deepEqual(f.counts(backup), [1, 1]);
  await restored.stop();
});

test("operator rotation rejects retired key epoch and restart fails when active key is missing", async (t) => {
  const f = await fixture(t);
  const original = await f.start("init");
  const old = await f.request(original);
  await original.stop();
  const newAuthority = await f.start("rotate");
  assert.equal(newAuthority.epoch, 2);
  assert.notEqual(newAuthority.keyId, original.keyId);
  await assert.rejects(newAuthority.recover(old.input), /denied/);
  const current = await f.request(newAuthority);
  await f.assertRewrap(await newAuthority.recover(current.input), current);
  await newAuthority.stop();
  f.examine((db) => db.prepare("DELETE FROM recovery_key WHERE id=?").run(newAuthority.keyId));
  await assert.rejects(f.start(), /unavailable/);
  assert.deepEqual(f.counts(), [1, 1]);
});
