import { Aes256Gcm, CipherSuite, DhkemP256HkdfSha256, HkdfSha256 } from "@hpke/core";
import { join, utf8, uuid } from "./format.mjs";

export const suite = new CipherSuite({ kem: new DhkemP256HkdfSha256(), kdf: new HkdfSha256(), aead: new Aes256Gcm() });
export const SUITE_ID = "0010:0001:0002";
export const recipientKey = () => crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, false, ["deriveBits"]);
export const publicBytes = async (key) => new Uint8Array(await crypto.subtle.exportKey("raw", key));
export const importRecipient = (raw) => suite.kem.deserializePublicKey(raw);
const info = utf8("BlueDrive/CSE/dek/v1");

function scopeBytes(context) {
  const kind = ["device", "personal", "organization"].indexOf(context.kind);
  if (kind < 0 || !Number.isSafeInteger(context.epoch) || context.epoch < 1) throw new RangeError("Invalid envelope context");
  const epoch = new Uint8Array(8);
  new DataView(epoch.buffer).setBigUint64(0, BigInt(context.epoch));
  return join(...["tenant", "workspace", "file", "version"].map((field) => uuid(context[field])),
    new Uint8Array([kind]), uuid(context.keyId), epoch);
}

export async function wrap(material, recipient, context) {
  if (material.length !== 32) throw new RangeError("Requires a 32-byte DEK");
  const result = await suite.seal({ recipientPublicKey: recipient, info }, material, scopeBytes(context));
  return { suite: SUITE_ID, enc: new Uint8Array(result.enc), ct: new Uint8Array(result.ct) };
}

export async function unwrap(envelope, recipient, context) {
  if (envelope.suite !== SUITE_ID || envelope.enc.length !== 65 || envelope.ct.length !== 48) throw new Error("Invalid envelope profile");
  // Cần cả public key để DHKEM không gọi export trên private key non-extractable.
  if (!recipient?.publicKey || !recipient.privateKey) throw new Error("Recipient key pair required");
  return new Uint8Array(await suite.open({ recipientKey: recipient, enc: envelope.enc, info }, envelope.ct, scopeBytes(context)));
}
