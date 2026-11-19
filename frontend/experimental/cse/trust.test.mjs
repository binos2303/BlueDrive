import assert from "node:assert/strict";
import test from "node:test";
import { equal, fixtureScope, random, sign, signingKey, verify } from "./format.mjs";
import { recipientKey, unwrap, wrap } from "./envelopes.mjs";
import {
  createEnrollment, deviceEntry, DirectoryTrust, fingerprint, openGrant, pinAuthority,
  signEntry, signGrant, verifyEnrollment,
} from "./trust.mjs";
import { createKit, newTicket, openKit, recoveryService, signApproval } from "./recovery.mjs";

const id = () => crypto.randomUUID();
const now = 10_000;

test("trusted device approves possession of both new keys once", async () => {
  const trusted = await signingKey();
  const next = await signingKey();
  const receiver = await recipientKey();
  const enrollment = await createEnrollment(id(), id(), id(), receiver.publicKey, next.publicKey, now + 100);
  const answer = await unwrap(enrollment.challenge, receiver, enrollment.context);
  const proof = await sign(next.privateKey, enrollment.payload);
  const approval = await sign(trusted.privateKey, enrollment.payload);
  await assert.rejects(verifyEnrollment(enrollment, random(32), proof, approval, trusted.publicKey, now));
  await assert.rejects(verifyEnrollment(enrollment, answer, proof, proof, trusted.publicKey, now));
  await assert.rejects(verifyEnrollment(enrollment, answer, proof, approval, trusted.publicKey, now + 101));
  await verifyEnrollment(enrollment, answer, proof, approval, trusted.publicKey, now);
  await assert.rejects(verifyEnrollment(enrollment, answer, proof, approval, trusted.publicKey, now));
});

test("independent authority pin, directory substitution, grants, rotation and revocation", async (t) => {
  const authority = await signingKey();
  const attacker = await signingKey();
  const device = await recipientKey();
  const rogue = await recipientKey();
  const doc = fixtureScope();
  const expectedDevice = { tenant: doc.tenant, subject: id(), device: id(), purpose: "receive" };
  const fields = { ...expectedDevice, keyId: id(), epoch: 7, status: "active" };
  const record = await signEntry(authority.privateKey, await deviceEntry(device.publicKey, fields));
  const anchor = await pinAuthority(authority.publicKey, await fingerprint(authority.publicKey));
  const trust = new DirectoryTrust(anchor);
  const authorized = await trust.accept(record, expectedDevice);
  const compromised = await deviceEntry(rogue.publicKey, fields);
  const producer = { ...await signingKey(), keyId: id() };
  const context = { ...doc, kind: "device", keyId: record.keyId, epoch: 7 };
  const material = random(32);
  const envelope = await wrap(material, authorized, context);
  const grantFields = { context, recipientDevice: record.device, recipientKeyEpoch: 7, signerKeyId: producer.keyId, expires: now + 40 };
  const grant = await signGrant(producer.privateKey, grantFields, envelope);
  const open = (opts = {}) => openGrant(trust, opts.entry ?? record, expectedDevice, device, producer,
    opts.grant ?? grant, opts.envelope ?? envelope, context, opts.now ?? now);
  assert.ok(equal(await open(), material));
  await t.test("out-of-band fingerprint rejects authority replacement", async () => {
    await assert.rejects(pinAuthority(attacker.publicKey, await fingerprint(authority.publicKey)));
  });
  await t.test("relay changes public key or enrolls rogue device", async () => {
    await assert.rejects(trust.accept({ ...record, publicKey: compromised.publicKey }, expectedDevice));
    await assert.rejects(trust.accept(await signEntry(attacker.privateKey, compromised), expectedDevice));
  });
  await t.test("Tenant, subject and key purpose remain checked", async () => {
    for (const patch of [{ tenant: id() }, { subject: id() }, { purpose: "sign" }]) {
      const substituted = await signEntry(authority.privateKey, { ...record, ...patch });
      await assert.rejects(trust.accept(substituted, expectedDevice));
    }
  });
  await t.test("expired and tampered signed grants remain unusable", async () => {
    await assert.rejects(open({ now: grant.expires }));
    const substituted = await wrap(random(32), rogue.publicKey, context);
    await assert.rejects(open({ envelope: substituted }));
    const bogus = await signGrant(attacker.privateKey, grantFields, envelope);
    await assert.rejects(open({ grant: bogus }));
  });
  await t.test("alternate authenticated key at same epoch is rejected", async () => {
    await assert.rejects(trust.accept(await signEntry(authority.privateKey, compromised), expectedDevice));
  });
  await t.test("revoked device denies envelope and rollback", async () => {
    const revoked = await signEntry(authority.privateKey, { ...record, epoch: 8, status: "revoked" });
    await assert.rejects(open({ entry: revoked }), /revoked/);
    await assert.rejects(open(), /rollback/);
  });
  await t.test("trusted rotation advances to a new device key, grants retain key binding", async () => {
    const rotated = await signEntry(authority.privateKey, { ...compromised, keyId: id(), epoch: 9 });
    await trust.accept(rotated, expectedDevice);
    await assert.rejects(open({ entry: rotated }), /authorization/);
    // TOFU không có checkpoint cũ trên thiết bị mới.
    const fresh = new DirectoryTrust(anchor);
    assert.ok(await fresh.accept(record, expectedDevice));
  });
});

test("Personal recovery from independent offline material and new device", async (t) => {
  const scope = fixtureScope();
  const identity = { tenant: scope.tenant, subject: id(), keyId: id(), generation: 1 };
  const session = { tenant: identity.tenant, subject: identity.subject, authenticated: true };
  const kit = await createKit(identity);
  const material = random(32);
  const context = { ...scope, kind: "personal", keyId: identity.keyId, epoch: identity.generation };
  const sealed = await wrap(material, kit.receivePublic, context);
  const newDevice = await recipientKey();
  const newSigner = await signingKey();
  const restored = await openKit(kit.bundle, kit.offlineMaterial, identity, session);
  const enrollment = await createEnrollment(identity.tenant, identity.subject, id(), newDevice.publicKey, newSigner.publicKey, now + 30);
  const proof = await unwrap(enrollment.challenge, newDevice, enrollment.context);
  const endorsement = await sign(restored.signer, enrollment.payload);
  assert.ok(await verify(kit.signerPublic, endorsement, enrollment.payload));
  await verifyEnrollment(enrollment, proof, await sign(newSigner.privateKey, enrollment.payload), endorsement, kit.signerPublic, now);
  const nextScope = { ...scope, kind: "device", keyId: id(), epoch: 1 };
  const restoredBytes = await unwrap(sealed, restored.receive, context);
  const next = await wrap(restoredBytes, newDevice.publicKey, nextScope);
  assert.ok(equal(material, await unwrap(next, newDevice, nextScope)));
  assert.equal(restored.receive.privateKey.extractable, false);
  const changed = kit.bundle.sealed.slice();
  changed[0] ^= 1;
  const rejected = {
    "wrong offline material": [kit.bundle, random(32), identity, session],
    "password reset without recovery kit": [kit.bundle, null, identity, { ...session, passwordReset: true }],
    "lost kit and final device": [null, kit.offlineMaterial, identity, session],
    "account or tenant isolation": [kit.bundle, kit.offlineMaterial, identity, { ...session, tenant: id() }],
    "cross-account": [kit.bundle, kit.offlineMaterial, identity, { ...session, subject: id() }],
    "rotated kit no longer current": [kit.bundle, kit.offlineMaterial, { ...identity, generation: 2 }, session],
    "session required": [kit.bundle, kit.offlineMaterial, identity, { ...session, authenticated: false }],
    "tampered encrypted bundle": [{ ...kit.bundle, sealed: changed }, kit.offlineMaterial, identity, session],
  };
  for (const [name, args] of Object.entries(rejected)) await t.test(name, () => assert.rejects(openKit(...args)));
});

test("Enterprise service checks independent approvals then rewraps for one recipient", async (t) => {
  const scope = fixtureScope();
  const org = await recipientKey();
  const next = await recipientKey();
  const keyId = id();
  const epoch = 8;
  const identities = Array.from({ length: 7 }, id);
  const [a, b, revoked, requester, recipient, orgAdmin, platformAdmin] = identities;
  const signers = new Map(await Promise.all(identities.map(async (owner) => [owner, await signingKey()])));
  const custodians = new Map([a, b, revoked, requester, recipient].map((owner) =>
    [owner, { tenant: scope.tenant, revoked: owner === revoked, publicKey: signers.get(owner).publicKey }]));
  const policy = { ...scope, recoveryKey: org, keyId, epoch, custodians, scopeAllowed: (ticket) => ticket.version === scope.version };
  const service = recoveryService(policy);
  const context = { ...scope, kind: "organization", keyId, epoch };
  const payload = random(32);
  const envelope = await wrap(payload, org.publicKey, context);
  const fields = { ...scope, keyId, epoch, caseId: id(), requester, recipient, recipientKeyId: id(),
    recipientFingerprint: await fingerprint(next.publicKey), expires: now + 1000, reason: "fixture-recovery" };
  const ticket = newTicket(fields, envelope);
  const approvals = (request, ...actors) => Promise.all(actors.map((owner) =>
    signApproval(request, owner, signers.get(owner).privateKey)));
  const approve = async (request, actors, item = envelope, clock = now) =>
    service.rewrap(request, await approvals(request, ...actors), item, next.publicKey, clock);
  for (const [name, attempt] of Object.entries({
    "one custodian": () => approve(ticket, [a]),
    "duplicate approval": () => approve(ticket, [a, a]),
    "wrong organization": () => approve({ ...ticket, tenant: id() }, [a, b]),
    "revoked custodian": () => approve(ticket, [a, revoked]),
    "expired approval": () => approve(ticket, [a, b], envelope, ticket.expires),
    "requester self-approval": () => approve(ticket, [a, requester]),
    "recipient self-approval": () => approve(ticket, [a, recipient]),
    "changed policy epoch": () => approve({ ...ticket, epoch: epoch + 1 }, [a, b]),
    "recovery outside scope": () => approve({ ...ticket, version: id() }, [a, b]),
    "Organization administrator without custody": () => approve(ticket, [a, orgAdmin]),
    "Platform administrator without custody": () => approve(ticket, [a, platformAdmin]),
    "substituted envelope": async () => approve(ticket, [a, b], await wrap(payload, org.publicKey, context)),
    "incorrect recovery envelope with matching ticket": async () => {
      const bad = await wrap(payload, next.publicKey, context);
      return approve(newTicket({ ...fields, caseId: id() }, bad), [a, b], bad);
    },
  })) await t.test(name, () => assert.rejects(attempt));
  const response = await approve(ticket, [a, b]);
  assert.ok(equal(payload, await unwrap(response, next, { ...scope, kind: "device", keyId: ticket.recipientKeyId, epoch })));
  await assert.rejects(approve(ticket, [a, b]));
  assert.deepEqual(service.audit, [{ caseId: ticket.caseId, tenant: scope.tenant, epoch, outcome: "rewrapped" }]);
  const rotated = await recipientKey();
  const newId = id();
  const replacement = recoveryService({ ...policy, keyId: newId, epoch: epoch + 1, recoveryKey: rotated });
  await assert.rejects(replacement.rewrap(ticket, await approvals(ticket, a, b), envelope, next.publicKey, now));
  const newEnvelope = await wrap(payload, rotated.publicKey, { ...context, keyId: newId, epoch: epoch + 1 });
  const newRequest = newTicket({ ...fields, keyId: newId, epoch: epoch + 1, caseId: id() }, newEnvelope);
  const rewrapped = await replacement.rewrap(newRequest, await approvals(newRequest, a, b), newEnvelope, next.publicKey, now);
  assert.ok(equal(payload, await unwrap(rewrapped, next, {
    ...scope, kind: "device", keyId: ticket.recipientKeyId, epoch: epoch + 1,
  })));
});
