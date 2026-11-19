import { sha256 } from "@noble/hashes/sha2.js";
import { equal, hex, random, sign, utf8, verify } from "./format.mjs";
import { importRecipient, publicBytes, unwrap, wrap } from "./envelopes.mjs";

export const message = (domain, values) => utf8(JSON.stringify([domain, ...values]));
export const fingerprint = async (key) => hex(sha256(new Uint8Array(await crypto.subtle.exportKey("spki", key))));
const entryFields = ["tenant", "subject", "device", "keyId", "purpose", "epoch", "status", "publicKey"];
const scopeFields = ["tenant", "workspace", "file", "version", "kind", "keyId", "epoch"];
const picked = (record, fields) => fields.map((field) => record[field]);

export async function pinAuthority(publicKey, expectedFingerprint) {
  if (await fingerprint(publicKey) !== expectedFingerprint) throw new Error("Independent fingerprint mismatch");
  return publicKey;
}

export async function createEnrollment(tenant, subject, device, receiver, signer, expires) {
  const nonce = crypto.randomUUID();
  const proof = random(32);
  const context = { tenant, workspace: subject, file: device, version: nonce, kind: "device", keyId: device, epoch: 1 };
  const challenge = await wrap(proof, receiver, context);
  const payload = message("p61-device-enrollment", [
    tenant, subject, device, nonce, expires, await fingerprint(receiver), await fingerprint(signer),
  ]);
  const expected = sha256(proof);
  proof.fill(0);
  return { challenge, context, payload, expires, consumed: false, expected, signer };
}

export async function verifyEnrollment(enrollment, proof, deviceSignature, endorsement, trustedDevice, now) {
  if (enrollment.consumed || now >= enrollment.expires
      || !equal(sha256(proof), enrollment.expected)
      || !await verify(enrollment.signer, deviceSignature, enrollment.payload)
      || !await verify(trustedDevice, endorsement, enrollment.payload)) {
    throw new Error("Trusted enrollment required");
  }
  if (enrollment.consumed) throw new Error("Enrollment already consumed");
  enrollment.consumed = true;
}

export async function signEntry(authority, entry) {
  return { ...entry, signature: await sign(authority, message("p61-directory", picked(entry, entryFields))) };
}

export class DirectoryTrust {
  #authority;
  #checkpoint = new Map();

  constructor(pinnedAuthority) {
    this.#authority = pinnedAuthority;
  }

  async accept(entry, scope) {
    const canonical = message("p61-directory", picked(entry, entryFields));
    if (["tenant", "subject", "device", "purpose"].some((field) => entry[field] !== scope[field])
        || !["receive", "sign"].includes(entry.purpose)
        || !["active", "revoked"].includes(entry.status)
        || !Number.isSafeInteger(entry.epoch) || entry.epoch < 1
        || !await verify(this.#authority, entry.signature, canonical)) {
      throw new Error("Directory authentication failed");
    }
    const scopeKey = JSON.stringify(picked(entry, ["tenant", "subject", "device", "purpose"]));
    const digest = hex(sha256(canonical));
    const last = this.#checkpoint.get(scopeKey);
    if (last && (last.epoch > entry.epoch || (last.epoch === entry.epoch && last.digest !== digest))) {
      throw new Error("Directory rollback or equivocation");
    }
    this.#checkpoint.set(scopeKey, { epoch: entry.epoch, digest });
    if (entry.status !== "active") throw new Error("Device revoked");
    const raw = Uint8Array.from(entry.publicKey.match(/../g) ?? [], (value) => Number.parseInt(value, 16));
    if (entry.purpose === "receive") return importRecipient(raw);
    return crypto.subtle.importKey("raw", raw, { name: "ECDSA", namedCurve: "P-256" }, true, ["verify"]);
  }
}

export async function deviceEntry(publicKey, data) {
  return { ...data, publicKey: hex(await publicBytes(publicKey)) };
}

const grantPayload = (grant, envelope) => message("p61-grant", [
  ...picked(grant.context, scopeFields), grant.recipientDevice, grant.recipientKeyEpoch, grant.signerKeyId, grant.expires,
  envelope.suite, hex(envelope.enc), hex(envelope.ct),
]);

export async function signGrant(producer, grant, envelope) {
  return { ...grant, signature: await sign(producer, grantPayload(grant, envelope)) };
}

export async function openGrant(trust, entry, expectedDevice, recipient, trustedProducer, grant, envelope, context, now) {
  const registered = await trust.accept(entry, expectedDevice);
  if (entry.purpose !== "receive" || entry.tenant !== context.tenant || entry.keyId !== context.keyId
      || entry.device !== grant.recipientDevice || entry.epoch !== grant.recipientKeyEpoch
      || !Number.isSafeInteger(grant.expires) || grant.expires <= now
      || trustedProducer.keyId !== grant.signerKeyId
      || scopeFields.some((field) => context[field] !== grant.context[field])
      || !await verify(trustedProducer.publicKey, grant.signature, grantPayload(grant, envelope))) {
    throw new Error("Grant authorization failed");
  }
  if (!equal(await publicBytes(registered), await publicBytes(recipient.publicKey))) throw new Error("Recipient binding mismatch");
  const material = await unwrap(envelope, recipient, context);
  try {
    await trust.accept(entry, expectedDevice);
    return material;
  } catch (error) {
    material.fill(0);
    throw error;
  }
}
