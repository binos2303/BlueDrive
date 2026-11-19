import { sha256 } from "@noble/hashes/sha2.js";

export const CHUNK = 1024 * 1024;
export const MAX_PLAINTEXT = 100 * CHUNK;
export const HEADER = 104;
export const PREFIX = 152;
export const TAG = 16;
export const MANIFEST = 0xffffffff;
export const PART = 8 * CHUNK;
const scopeFields = ["tenant", "workspace", "file", "version"];
export const utf8 = (value) => new TextEncoder().encode(value);
const magic = utf8("BLUDCSE1");

export function bytes(hex) {
  if (!/^(?:[0-9a-f]{2})*$/i.test(hex)) throw new TypeError("Invalid hex");
  return Uint8Array.from(hex.match(/../g) ?? [], (value) => Number.parseInt(value, 16));
}

export const hex = (value) => Array.from(new Uint8Array(value), (b) => b.toString(16).padStart(2, "0")).join("");
export const random = (length) => crypto.getRandomValues(new Uint8Array(length));
export const fixtureScope = () => Object.fromEntries(scopeFields.map((field) => [field, crypto.randomUUID()]));

export function join(...items) {
  const out = new Uint8Array(items.reduce((length, item) => length + item.length, 0));
  let offset = 0;
  for (const item of items) {
    out.set(item, offset);
    offset += item.length;
  }
  return out;
}

export function equal(left, right) {
  if (left.length !== right.length) return false;
  let diff = 0;
  for (let i = 0; i < left.length; i++) diff |= left[i] ^ right[i];
  return diff === 0;
}

export function uuid(value) {
  if (typeof value !== "string" || !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(value)) {
    throw new TypeError("Expected canonical UUID");
  }
  return bytes(value.replaceAll("-", ""));
}

export function wireSize(size) {
  if (!Number.isSafeInteger(size) || size < 0 || size > MAX_PLAINTEXT) throw new RangeError("Plaintext exceeds profile");
  return PREFIX + size + TAG * Math.ceil(size / CHUNK);
}

export function encodeHeader(scope, size, noncePrefix) {
  wireSize(size);
  if (noncePrefix.length !== 8) throw new RangeError("Invalid nonce prefix");
  const header = new Uint8Array(HEADER);
  const view = new DataView(header.buffer);
  header.set(magic);
  view.setUint16(8, 1);
  view.setUint16(10, HEADER);
  scopeFields.forEach((field, index) => header.set(uuid(scope[field]), 16 + index * 16));
  view.setBigUint64(80, BigInt(size));
  view.setUint32(88, CHUNK);
  view.setUint32(92, Math.ceil(size / CHUNK));
  header.set(noncePrefix, 96);
  return header;
}

export function parseHeader(header, wireLength, scope) {
  if (header.length !== HEADER || !equal(header.subarray(0, 8), magic)) throw new Error("Invalid header");
  const view = new DataView(header.buffer, header.byteOffset, header.length);
  if (view.getUint16(8) !== 1 || view.getUint16(10) !== HEADER || view.getUint32(12) !== 0 || view.getUint32(88) !== CHUNK) {
    throw new Error("Unsupported format");
  }
  const rawSize = view.getBigUint64(80);
  if (rawSize > BigInt(MAX_PLAINTEXT)) throw new RangeError("Plaintext exceeds profile");
  const size = Number(rawSize);
  const count = Math.ceil(size / CHUNK);
  if (view.getUint32(92) !== count || wireLength !== wireSize(size)) throw new Error("Invalid ciphertext length");
  for (const [index, field] of scopeFields.entries()) {
    if (!equal(header.subarray(16 + index * 16, 32 + index * 16), uuid(scope[field]))) throw new Error("Scope mismatch");
  }
  return { size, count };
}

export function recordParameters(header, index, length, count) {
  const manifest = index === MANIFEST;
  if (!Number.isInteger(count) || count < 0 || count > Math.ceil(MAX_PLAINTEXT / CHUNK)
      || !Number.isInteger(index) || index < 0 || (!manifest && index >= count)
      || !Number.isInteger(length) || (manifest ? length !== 32 : length < 1 || length > CHUNK)) {
    throw new RangeError("Invalid record index or length");
  }
  const iv = new Uint8Array(12);
  iv.set(header.subarray(96, 104));
  new DataView(iv.buffer).setUint32(8, index);
  const record = new Uint8Array(9);
  const view = new DataView(record.buffer);
  view.setUint8(0, manifest ? 1 : 0);
  view.setUint32(1, index);
  view.setUint32(5, length);
  return { name: "AES-GCM", iv, tagLength: 128, additionalData: join(utf8("BlueDrive/CSE/aead/v1\0"), header, record) };
}

export async function aesKey(material, usages) {
  if (material.length !== 32) throw new RangeError("Requires AES-256");
  return crypto.subtle.importKey("raw", material, "AES-GCM", false, usages);
}

export const signingKey = (extractable = false) =>
  crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, extractable, ["sign", "verify"]);
export const sign = async (key, payload) =>
  new Uint8Array(await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, payload));
export const verify = (key, signature, payload) => signature.length === 64 &&
  crypto.subtle.verify({ name: "ECDSA", hash: "SHA-256" }, key, signature, payload);

const read = async (blob, start, end) => new Uint8Array(await blob.slice(start, end).arrayBuffer());
const signPayload = (keyId, prefix, digest) => join(utf8("BlueDrive/CSE/sign/v1\0"), uuid(keyId), prefix, digest);

async function digestBlob(blob) {
  const hash = sha256.create();
  for (let offset = 0; offset < blob.size; offset += CHUNK) hash.update(await read(blob, offset, offset + CHUNK));
  return hash.digest();
}

// Mỗi seal dùng DEK mới, và receipt chỉ có giá trị sau khi caller đã chốt spool.
export async function seal(blob, scope, producer, write, observe = () => {}) {
  const header = encodeHeader(scope, blob.size, random(8));
  const count = Math.ceil(blob.size / CHUNK);
  const material = random(32);
  const key = await aesKey(material, ["encrypt"]);
  const expected = await digestBlob(blob);
  const manifest = new Uint8Array(await crypto.subtle.encrypt(recordParameters(header, MANIFEST, 32, count), key, expected));
  const prefix = join(header, manifest);
  const ciphertextHash = sha256.create().update(prefix);
  const plaintextHash = sha256.create();
  try {
    await write(prefix);
    for (let index = 0; index < count; index++) {
      const plain = await read(blob, index * CHUNK, (index + 1) * CHUNK);
      plaintextHash.update(plain);
      const ciphertext = new Uint8Array(await crypto.subtle.encrypt(recordParameters(header, index, plain.length, count), key, plain));
      observe(plain.length + ciphertext.length, 2);
      ciphertextHash.update(ciphertext);
      await write(ciphertext);
    }
    if (!equal(plaintextHash.digest(), expected)) throw new Error("Source changed during seal");
    const digest = ciphertextHash.digest();
    const payload = signPayload(producer.keyId, prefix, digest);
    const signature = producer.sign ? await producer.sign(payload) : await sign(producer.privateKey, payload);
    return { material, descriptor: { keyId: producer.keyId, digest, signature, wireLength: wireSize(blob.size) } };
  } catch (error) {
    material.fill(0);
    throw error;
  }
}

async function* plaintextRecords(blob, key, header, size, count, observe) {
  let offset = PREFIX;
  for (let index = 0; index < count; index++) {
    const length = Math.min(CHUNK, size - index * CHUNK);
    const ciphertext = await read(blob, offset, offset + length + TAG);
    const plain = new Uint8Array(await crypto.subtle.decrypt(recordParameters(header, index, length, count), key, ciphertext));
    observe(plain.length + ciphertext.length, 2);
    yield plain;
    offset += ciphertext.length;
  }
}

async function verifiedContainer(blob, scope, descriptor, producer) {
  if (blob.size < PREFIX || blob.size > wireSize(MAX_PLAINTEXT)) throw new Error("Invalid ciphertext length");
  const prefix = await read(blob, 0, PREFIX);
  const header = prefix.subarray(0, HEADER);
  const { size, count } = parseHeader(header, blob.size, scope);
  if (descriptor.keyId !== producer.keyId || descriptor.wireLength !== blob.size || descriptor.digest.length !== 32
      || !await verify(producer.publicKey, descriptor.signature, signPayload(producer.keyId, prefix, descriptor.digest))) {
    throw new Error("Invalid producer signature");
  }
  if (!equal(await digestBlob(blob), descriptor.digest)) throw new Error("Ciphertext digest mismatch");
  return { prefix, header, size, count };
}

export async function openVerified(blob, scope, descriptor, material, producer, exportChunk, observe = () => {}) {
  const { prefix, header, size, count } = await verifiedContainer(blob, scope, descriptor, producer);
  const key = await aesKey(material, ["decrypt"]);
  const expected = new Uint8Array(await crypto.subtle.decrypt(recordParameters(header, MANIFEST, 32, count), key, prefix.subarray(HEADER)));
  const hash = sha256.create();
  for await (const plain of plaintextRecords(blob, key, header, size, count, observe)) hash.update(plain);
  if (!equal(hash.digest(), expected)) throw new Error("Plaintext digest mismatch");
  // Chỉ xuất từ Blob snapshot vừa xác minh toàn file. Không giữ cả plaintext trong RAM.
  for await (const plain of plaintextRecords(blob, key, header, size, count, observe)) await exportChunk(plain);
}

export async function resumeSealed(blob, descriptor, scope, producer) {
  if (!blob || !descriptor || !scope || !producer) throw new Error("Sealed receipt unavailable; new intent required");
  await verifiedContainer(blob, scope, descriptor, producer);
  return (part) => {
    if (!Number.isInteger(part) || part < 1 || part > Math.ceil(blob.size / PART)) throw new RangeError("Invalid part");
    return blob.slice((part - 1) * PART, part * PART);
  };
}
