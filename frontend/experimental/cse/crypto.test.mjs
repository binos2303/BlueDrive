import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { sha256 } from "@noble/hashes/sha2.js";
import { Aes128Gcm, CipherSuite, DhkemP256HkdfSha256, HkdfSha256 } from "@hpke/core";
import {
  aesKey, bytes, CHUNK, encodeHeader, equal, fixtureScope, HEADER, hex, join, MANIFEST, MAX_PLAINTEXT,
  openVerified, PART, PREFIX, random, recordParameters, resumeSealed, seal, sign, signingKey, utf8, uuid, wireSize,
} from "./format.mjs";
import { importRecipient, publicBytes, recipientKey, suite, unwrap, wrap } from "./envelopes.mjs";

const vectors = JSON.parse(readFileSync(new URL("vectors.json", import.meta.url), "utf8"));

for (const vector of vectors.gcm) {
  test(`NIST CAVP AES-256-GCM, plaintext ${vector.PT.length / 2} bytes`, async () => {
    const key = await aesKey(bytes(vector.Key), ["encrypt", "decrypt"]);
    const params = { name: "AES-GCM", iv: bytes(vector.IV), additionalData: bytes(vector.AAD), tagLength: 128 };
    const ciphertext = new Uint8Array(await crypto.subtle.encrypt(params, key, bytes(vector.PT)));
    assert.equal(hex(ciphertext), vector.CT + vector.Tag);
    assert.ok(equal(new Uint8Array(await crypto.subtle.decrypt(params, key, ciphertext)), bytes(vector.PT)));
  });
}

test("RFC 9180 exact suite, encapsulation and three sequential AAD vectors", async () => {
  const { ikmR, ikmE, info, enc, encryptions } = vectors.hpke;
  const pair = await suite.kem.deriveKeyPair(bytes(ikmR));
  const sender = await suite.createSenderContext({ recipientPublicKey: pair.publicKey, info: bytes(info), ekm: bytes(ikmE) });
  assert.equal(hex(sender.enc), enc);
  const receiver = await suite.createRecipientContext({ recipientKey: pair, info: bytes(info), enc: bytes(enc) });
  for (const { aad, pt, ct } of encryptions) {
    assert.equal(hex(await sender.seal(bytes(pt), bytes(aad))), ct);
    assert.equal(hex(await receiver.open(bytes(ct), bytes(aad))), pt);
  }
});

function reference(request) {
  const python = process.env.P61_PYTHON ?? "python";
  const script = fileURLToPath(new URL("reference.py", import.meta.url));
  const run = spawnSync(python, ["-B", script], { input: JSON.stringify(request) + "\n", encoding: "utf8", timeout: 15000 });
  assert.equal(run.error?.code ?? run.status, 0, `Reference process failed: ${run.stderr?.trim() || "unavailable"}`);
  return JSON.parse(run.stdout);
}

test("PyCA seals to a non-extractable WebCrypto recipient", async () => {
  const pair = await recipientKey();
  assert.equal(pair.privateKey.extractable, false);
  const payload = random(32);
  const wire = bytes(reference({ action: "seal", public: hex(await publicBytes(pair.publicKey)), fixture: hex(payload) }).wire);
  const args = { enc: wire.subarray(0, 65), info: utf8("BlueDrive/P6.1/interop") };
  await assert.rejects(suite.open({ ...args, recipientKey: pair.privateKey }, wire.subarray(65)), /not extractable/i);
  const opened = new Uint8Array(await suite.open({ ...args, recipientKey: pair }, wire.subarray(65)));
  assert.ok(equal(payload, opened));
});

test("@hpke/core seals and independent PyCA opens", async () => {
  const pair = await crypto.subtle.generateKey({ name: "ECDH", namedCurve: "P-256" }, true, ["deriveBits"]);
  const payload = random(32);
  const { enc, ct } = await suite.seal({ recipientPublicKey: pair.publicKey, info: utf8("BlueDrive/P6.1/interop") }, payload);
  const fixturePkcs8 = hex(await crypto.subtle.exportKey("pkcs8", pair.privateKey));
  const reply = reference({ action: "open", fixturePkcs8, wire: hex(join(new Uint8Array(enc), new Uint8Array(ct))) });
  assert.ok(reply.digest === hex(sha256(payload)), "Independent recipient authenticated the same synthetic bytes");
});

test("HPKE rejects context, wrong keys/suite, tag, enc and ciphertext changes", async (t) => {
  const pair = await recipientKey();
  const other = await recipientKey();
  const context = { ...fixtureScope(), kind: "device", keyId: crypto.randomUUID(), epoch: 7 };
  const material = random(32);
  const envelope = await wrap(material, pair.publicKey, context);
  assert.ok(equal(material, await unwrap(envelope, pair, context)));
  const standaloneInfo = utf8("p61-correct-info");
  const standalone = await suite.seal({ recipientPublicKey: pair.publicKey, info: standaloneInfo }, material);
  const cases = {
    "wrong private key": () => unwrap(envelope, other, context),
    "different tenant AAD": () => unwrap(envelope, pair, { ...context, tenant: crypto.randomUUID() }),
    "different version AAD": () => unwrap(envelope, pair, { ...context, version: crypto.randomUUID() }),
    "different key id AAD": () => unwrap(envelope, pair, { ...context, keyId: crypto.randomUUID() }),
    "wrong suite field": () => unwrap({ ...envelope, suite: "wrong" }, pair, context),
    "invalid recipient key": () => importRecipient(new Uint8Array(65)),
    "modified encapsulated key": () => unwrap({ ...envelope, enc: flip(envelope.enc, 1) }, pair, context),
    "modified ciphertext": () => unwrap({ ...envelope, ct: flip(envelope.ct, 0) }, pair, context),
    "modified tag": () => unwrap({ ...envelope, ct: flip(envelope.ct, 47) }, pair, context),
    "wrong info": () => suite.open({ recipientKey: pair, enc: standalone.enc, info: utf8("different-info") }, standalone.ct),
    "wrong cryptographic suite": () => new CipherSuite({
      kem: new DhkemP256HkdfSha256(), kdf: new HkdfSha256(), aead: new Aes128Gcm(),
    }).open({ recipientKey: pair, enc: standalone.enc, info: standaloneInfo }, standalone.ct),
  };
  for (const [name, attempt] of Object.entries(cases)) await t.test(name, () => assert.rejects(attempt));
});

function flip(value, offset) {
  const changed = value.slice();
  changed[offset] ^= 1;
  return changed;
}

test("cse_v1 deterministic offsets, nonce, AAD and PyCA frame digest", async () => {
  const scope = Object.fromEntries(["tenant", "workspace", "file", "version"].map(
    (field, index) => [field, "00000000-0000-4000-8000-" + String(index + 1).padStart(12, "0")],
  ));
  const data = utf8("BlueDrive public frame");
  const header = encodeHeader(scope, data.length, new Uint8Array([0, 1, 2, 3, 4, 5, 6, 7]));
  const key = await aesKey(sha256(utf8("BlueDrive P6.1 public format vector")), ["encrypt", "decrypt"]);
  const manifest = new Uint8Array(await crypto.subtle.encrypt(recordParameters(header, MANIFEST, 32, 1), key, sha256(data)));
  const parameters = recordParameters(header, 0, data.length, 1);
  const record = new Uint8Array(await crypto.subtle.encrypt(parameters, key, data));
  const frame = join(header, manifest, record);
  assert.equal(frame.length, wireSize(data.length));
  assert.equal(hex(sha256(frame)), vectors.frameSha256);
  await assert.rejects(crypto.subtle.decrypt({ ...parameters, iv: flip(parameters.iv, 11) }, key, record));
  await assert.rejects(crypto.subtle.decrypt({ ...parameters, additionalData: flip(parameters.additionalData, 2) }, key, record));
});

function fixtureBlob(size) {
  const block = new Uint8Array(CHUNK).fill(0x6d);
  const parts = Array.from({ length: Math.floor(size / CHUNK) }, () => block);
  parts.push(block.subarray(0, size % CHUNK));
  return new Blob(parts);
}

async function sealedFixture(data, scope = fixtureScope()) {
  const producer = { ...await signingKey(), keyId: crypto.randomUUID() };
  const parts = [];
  const result = await seal(data, scope, producer, (part) => parts.push(part));
  return { ...result, producer, scope, blob: new Blob(parts) };
}

for (const size of [0, 1, CHUNK - 1, CHUNK, CHUNK + 1, 3 * CHUNK + 7, MAX_PLAINTEXT]) {
  test(`cse_v1 round trip size ${size}`, async () => {
    const input = fixtureBlob(size);
    const { blob, descriptor, scope, material, producer } = await sealedFixture(input);
    assert.equal(descriptor.signature.length, 64);
    assert.equal(blob.size, wireSize(size));
    let exported = 0;
    await openVerified(blob, scope, descriptor, material, producer, (chunk) => {
      assert.ok(chunk.every((b) => b === 0x6d));
      exported += chunk.length;
    });
    assert.equal(exported, size);
  });
}

test("trimmed, reordered, duplicated or modified bytes never reach the export sink", async (t) => {
  const x = await sealedFixture(fixtureBlob(3 * CHUNK));
  const wire = new Uint8Array(await x.blob.arrayBuffer());
  const frame = CHUNK + 16;
  const part = (i) => wire.subarray(PREFIX + i * frame, PREFIX + (i + 1) * frame);
  const prefix = wire.subarray(0, PREFIX);
  const overflow = wire.slice();
  new DataView(overflow.buffer).setBigUint64(80, 1n << 63n);
  const cases = {
    "empty": [new Blob([])],
    "truncated": [x.blob.slice(0, -1)],
    "append": [new Blob([wire, new Uint8Array([5])])],
    "wrong header": [new Blob([flip(wire, 0)])],
    "unknown flags": [new Blob([flip(wire, 15)])],
    "forged chunk count": [new Blob([flip(wire, 95)])],
    "length overflow": [new Blob([overflow])],
    "missing chunk": [new Blob([prefix, part(0), part(2)])],
    "reordered chunks": [new Blob([prefix, part(1), part(0), part(2)])],
    "duplicate chunk": [new Blob([prefix, part(0), part(0), part(2)])],
    "wrong DEK": [x.blob, x.scope, x.descriptor, random(32)],
    "wrong Tenant": [x.blob, { ...x.scope, tenant: crypto.randomUUID() }],
    "wrong Workspace": [x.blob, { ...x.scope, workspace: crypto.randomUUID() }],
    "wrong version": [x.blob, { ...x.scope, version: crypto.randomUUID() }],
    "wrong producer signature": [x.blob, x.scope, { ...x.descriptor, signature: flip(x.descriptor.signature, 1) }],
  };
  let emitted = 0;
  const tryOpen = (blob, scope = x.scope, descriptor = x.descriptor, material = x.material) =>
    openVerified(blob, scope, descriptor, material, x.producer, () => emitted++);
  for (const [name, input] of Object.entries(cases)) await t.test(name, () => assert.rejects(tryOpen(...input)));
  for (const [name, offset] of [["manifest tag", HEADER + 47], ["record ciphertext", PREFIX], ["record tag", wire.length - 1]]) {
    await t.test(name, async () => {
      const changed = flip(wire, offset);
      // Chữ ký hợp lệ trong fixture cô lập bước kiểm AEAD khỏi bước kiểm digest dây.
      const digest = sha256(changed);
      const signature = await sign(x.producer.privateKey, join(utf8("BlueDrive/CSE/sign/v1\0"),
        uuid(x.producer.keyId), changed.subarray(0, PREFIX), digest));
      await assert.rejects(tryOpen(new Blob([changed]), x.scope, { ...x.descriptor, digest, signature }));
    });
  }
  assert.equal(emitted, 0);
});

test("nonce counters are unique and retry uses sealed 8 MiB parts", async () => {
  const scope = fixtureScope();
  const header = encodeHeader(scope, MAX_PLAINTEXT, random(8));
  const count = Math.ceil(MAX_PLAINTEXT / CHUNK);
  const ivs = [...Array(count).keys(), MANIFEST].map((index) =>
    hex(recordParameters(header, index, index === MANIFEST ? 32 : CHUNK, count).iv));
  assert.equal(new Set(ivs).size, count + 1);
  assert.throws(() => recordParameters(header, count, CHUNK, count));
  assert.throws(() => recordParameters(header, 0, CHUNK, count + 1));
  const first = await sealedFixture(fixtureBlob(PART + 7), scope);
  const getPart = await resumeSealed(first.blob, first.descriptor, first.scope, first.producer);
  assert.equal(getPart(1).size, PART);
  assert.ok(equal(new Uint8Array(await getPart(2).arrayBuffer()), new Uint8Array(await getPart(2).arrayBuffer())));
  assert.throws(() => getPart(3));
  await assert.rejects(resumeSealed(first.blob.slice(1), first.descriptor, first.scope, first.producer));
  await assert.rejects(resumeSealed(first.blob, null));
  const modified = flip(new Uint8Array(await first.blob.arrayBuffer()), PREFIX);
  await assert.rejects(resumeSealed(new Blob([modified]), {
    ...first.descriptor, digest: sha256(modified),
  }, first.scope, first.producer), /signature/);
  const next = await sealedFixture(fixtureBlob(PART + 7), { ...scope, version: crypto.randomUUID() });
  assert.ok(!equal(first.material, next.material));
  assert.ok(!equal(first.descriptor.digest, next.descriptor.digest));
});
