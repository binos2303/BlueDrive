import { sha256 } from "@noble/hashes/sha2.js";
import { aesKey, bytes, hex, join, random, sign, signingKey, verify } from "./format.mjs";
import { importRecipient, publicBytes, unwrap, wrap } from "./envelopes.mjs";
import { fingerprint, message } from "./trust.mjs";

const kitIdentity = ["tenant", "subject", "keyId", "generation"];
const own = (record, fields) => fields.map((field) => record[field]);
const kitAad = (bundle) => message("p61-personal-kit", [bundle.version, ...own(bundle, kitIdentity), bundle.receivePublicHex]);

export async function createKit(identity) {
  const receive = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const signer = await signingKey(true);
  const offlineMaterial = random(32);
  const bundle = { ...identity, version: 1, iv: random(12), receivePublicHex: hex(await publicBytes(receive.publicKey)) };
  const rawReceive = new Uint8Array(await crypto.subtle.exportKey("pkcs8", receive.privateKey));
  const rawSign = new Uint8Array(await crypto.subtle.exportKey("pkcs8", signer.privateKey));
  const lengths = new Uint8Array(4);
  new DataView(lengths.buffer).setUint16(0, rawReceive.length);
  new DataView(lengths.buffer).setUint16(2, rawSign.length);
  const payload = join(lengths, rawReceive, rawSign);
  rawReceive.fill(0);
  rawSign.fill(0);
  try {
    const key = await aesKey(offlineMaterial, ["encrypt"]);
    bundle.sealed = new Uint8Array(await crypto.subtle.encrypt(
      { name: "AES-GCM", iv: bundle.iv, additionalData: kitAad(bundle), tagLength: 128 }, key, payload,
    ));
    return { bundle, offlineMaterial, receivePublic: receive.publicKey, signerPublic: signer.publicKey };
  } finally {
    payload.fill(0);
  }
}

export async function openKit(bundle, offlineMaterial, signedIdentity, session) {
  if (!session.authenticated || !bundle || !offlineMaterial || bundle.version !== 1
      || bundle.tenant !== session.tenant || bundle.subject !== session.subject
      || bundle.iv.length !== 12 || bundle.sealed.length > 2048 || !/^04[0-9a-f]{128}$/.test(bundle.receivePublicHex)
      || kitIdentity.some((field) => bundle[field] !== signedIdentity[field])) {
    throw new Error("Kit missing or wrong recovery identity");
  }
  const key = await aesKey(offlineMaterial, ["decrypt"]);
  const decoded = new Uint8Array(await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: bundle.iv, additionalData: kitAad(bundle), tagLength: 128 }, key, bundle.sealed,
  ));
  try {
    if (decoded.length < 4) throw new Error("Invalid recovery key framing");
    const view = new DataView(decoded.buffer);
    const length1 = view.getUint16(0);
    const length2 = view.getUint16(2);
    if (length1 < 1 || length2 < 1 || 4 + length1 + length2 !== decoded.length) throw new Error("Invalid recovery key framing");
    const privateKey = await crypto.subtle.importKey("pkcs8", decoded.subarray(4, 4 + length1),
      { name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
    const receive = { privateKey, publicKey: await importRecipient(bytes(bundle.receivePublicHex)) };
    const signer = await crypto.subtle.importKey("pkcs8", decoded.subarray(4 + length1),
      { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
    return { receive, signer };
  } finally {
    decoded.fill(0);
  }
}

const envelopeDigest = (envelope) => hex(sha256(message("p61-recovery-envelope", [
  envelope.suite, hex(envelope.enc), hex(envelope.ct),
])));
const ticketFields = ["caseId", "tenant", "workspace", "file", "version", "requester", "recipient",
  "recipientKeyId", "recipientFingerprint", "keyId", "epoch", "expires", "reason", "envelopeDigest"];
const approvalPayload = (ticket, approver) => message("p61-recovery-approval", [...own(ticket, ticketFields), approver]);
const contentScope = ["tenant", "workspace", "file", "version"];

export async function signApproval(ticket, approver, privateKey) {
  return { approver, signature: await sign(privateKey, approvalPayload(ticket, approver)) };
}

export function newTicket(fields, envelope) {
  return { ...fields, envelopeDigest: envelopeDigest(envelope) };
}

// Hai chữ ký cấp quyền cho cùng một service cầm khóa. Fixture chỉ đo quorum chính sách.
export function recoveryService({ tenant, recoveryKey, keyId, epoch, custodians, scopeAllowed }) {
  const handled = new Set();
  const audit = [];
  return {
    audit,
    async rewrap(ticket, approvals, envelope, recipientPublic, now) {
      if (ticket.tenant !== tenant || ticket.keyId !== keyId || ticket.epoch !== epoch
          || !Number.isSafeInteger(ticket.expires) || ticket.expires <= now || !scopeAllowed(ticket)
          || !ticket.reason || ticket.envelopeDigest !== envelopeDigest(envelope)
          || ticket.recipientFingerprint !== await fingerprint(recipientPublic)) {
        throw new Error("Recovery request rejected");
      }
      const accepted = new Set();
      for (const { approver, signature } of approvals) {
        const custodian = custodians.get(approver);
        if (!custodian || custodian.tenant !== tenant || custodian.revoked
            || approver === ticket.requester || approver === ticket.recipient
            || !await verify(custodian.publicKey, signature, approvalPayload(ticket, approver))) {
          throw new Error("Invalid independent approval");
        }
        accepted.add(approver);
      }
      if (accepted.size < 2 || handled.has(ticket.caseId)) throw new Error("Approval quorum missing or replayed");
      handled.add(ticket.caseId);
      const scope = Object.fromEntries(contentScope.map((field) => [field, ticket[field]]));
      const material = await unwrap(envelope, recoveryKey, { ...scope, keyId, epoch, kind: "organization" });
      try {
        const wrapped = await wrap(material, recipientPublic, { ...scope, kind: "device", keyId: ticket.recipientKeyId, epoch });
        audit.push({ caseId: ticket.caseId, tenant, epoch, outcome: "rewrapped" });
        return wrapped;
      } finally {
        material.fill(0);
      }
    },
  };
}
