import { readFile } from "node:fs/promises";
import { DatabaseSync } from "node:sqlite";
import { hex, verify } from "./format.mjs";
import { importRecipient, publicBytes, SUITE_ID, unwrap, wrap } from "./envelopes.mjs";
import { fingerprint } from "./trust.mjs";
import { approvalPayload, envelopeDigest, requestDigest, requestPayload, scopeOf } from "./custody-protocol.mjs";

const id = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const digest = /^[0-9a-f]{64}$/;
const mode = process.argv[2];
const cfg = JSON.parse(await readFile(process.argv[3], "utf8"));
const db = new DatabaseSync(process.argv[4]);
db.exec("PRAGMA foreign_keys=ON; PRAGMA synchronous=FULL; PRAGMA busy_timeout=4000");
const curve = { name: "ECDH", namedCurve: "P-256" };
const signerCurve = { name: "ECDSA", namedCurve: "P-256" };
const bytesOf = (value, length) => value instanceof Uint8Array && value.length === length;
const failAt = (point) => { if (process.argv[5] === point) process.exit(97); };

async function keyMaterial() {
  const pair = await crypto.subtle.generateKey(curve, true, ["deriveBits"]);
  return { privateDer: new Uint8Array(await crypto.subtle.exportKey("pkcs8", pair.privateKey)), publicRaw: await publicBytes(pair.publicKey) };
}

if (!id.test(cfg.tenant) || cfg.custodians.length !== 3 || new Set(cfg.custodians.map((row) => row.id)).size !== 3
    || new Set(cfg.custodians.map((row) => row.publicKey)).size !== 3) throw new Error("Authority policy invalid");
if (mode === "init") {
  const material = await keyMaterial();
  try {
    db.exec(`BEGIN IMMEDIATE;
      CREATE TABLE authority (id INTEGER PRIMARY KEY CHECK (id=1), tenant TEXT NOT NULL, key_id TEXT NOT NULL, epoch INTEGER NOT NULL);
      CREATE TABLE recovery_key (id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, private_der BLOB NOT NULL, public_raw BLOB NOT NULL);
      CREATE TABLE cases (
        id TEXT PRIMARY KEY, nonce TEXT UNIQUE NOT NULL, target TEXT UNIQUE NOT NULL, request TEXT NOT NULL,
        enc BLOB NOT NULL, ct BLOB NOT NULL, epoch INTEGER NOT NULL
      );
      CREATE TABLE outbox (
        case_id TEXT PRIMARY KEY REFERENCES cases(id), tenant TEXT NOT NULL, epoch INTEGER NOT NULL,
        approvals TEXT NOT NULL, committed INTEGER NOT NULL
      );`);
    const keyId = crypto.randomUUID();
    db.prepare("INSERT INTO authority VALUES (1,?,?,1)").run(cfg.tenant, keyId);
    db.prepare("INSERT INTO recovery_key VALUES (?,1,?,?)").run(keyId, material.privateDer, material.publicRaw);
    db.exec("COMMIT");
  } finally {
    material.privateDer.fill(0);
  }
}
if (mode === "rotate") {
  const material = await keyMaterial();
  try {
    db.exec("BEGIN IMMEDIATE");
    const old = db.prepare("SELECT * FROM authority WHERE id=1").get();
    if (old.tenant !== cfg.tenant) throw new Error("Authority scope mismatch");
    const keyId = crypto.randomUUID();
    db.prepare("INSERT INTO recovery_key VALUES (?,?,?,?)").run(keyId, old.epoch + 1, material.privateDer, material.publicRaw);
    db.prepare("UPDATE authority SET key_id=?, epoch=epoch+1 WHERE id=1").run(keyId);
    db.exec("COMMIT");
  } finally {
    material.privateDer.fill(0);
  }
}

function activeKey() {
  const row = db.prepare(`SELECT a.tenant, a.key_id, a.epoch, k.public_raw, k.private_der
    FROM authority a JOIN recovery_key k ON a.key_id=k.id AND a.epoch=k.epoch WHERE a.id=1`).get();
  if (row?.tenant !== cfg.tenant || !bytesOf(row.public_raw, 65) || !row.private_der?.length) throw new Error("Recovery material missing");
  return row;
}

const register = async (rows) => new Map(await Promise.all(rows.map(async (row) => [
  row.id, { ...row, key: await crypto.subtle.importKey("raw", Buffer.from(row.publicKey, "hex"), signerCurve, true, ["verify"]) },
])));
const requesters = await register(cfg.requesters);
const custodians = await register(cfg.custodians);
if (new Set([...requesters.values(), ...custodians.values()].map((row) => row.publicKey)).size
    !== requesters.size + custodians.size) throw new Error("Recovery roles must use distinct keys");
const allowedRecipients = new Map(cfg.recipients.map((row) => [row.id, row]));
const initial = activeKey();
initial.private_der.fill(0);
process.send({ kind: "ready", keyId: initial.key_id, epoch: initial.epoch, publicRaw: initial.public_raw });

async function recover({ ticket, requestSignature, approvals, envelope, recipientRaw }) {
  const now = Date.now();
  if (!ticket || ticket.tenant !== cfg.tenant
      || !["caseId", "workspace", "file", "version", "requester", "recipient", "recipientKeyId", "keyId"].every((key) => id.test(ticket[key]))
      || !digest.test(ticket.nonce) || !Number.isSafeInteger(ticket.epoch) || !Number.isSafeInteger(ticket.expires)
      || ticket.expires <= now || ticket.expires > now + 300_000 || typeof ticket.reason !== "string"
      || ticket.reason.length < 1 || ticket.reason.length > 128 || !bytesOf(recipientRaw, 65)
      || envelope?.suite !== SUITE_ID || !bytesOf(envelope.enc, 65) || !bytesOf(envelope.ct, 48)
      || ticket.envelopeDigest !== envelopeDigest(envelope) || !Array.isArray(approvals) || approvals.length > 3
      || !bytesOf(requestSignature, 64)) throw new Error("Recovery request rejected");
  const requester = requesters.get(ticket.requester);
  const recipient = allowedRecipients.get(ticket.recipient);
  if (!requester || requester.revoked || !requester.workspaces.includes(ticket.workspace)
      || !recipient || recipient.revoked || recipient.keyId !== ticket.recipientKeyId || recipient.publicKey !== hex(recipientRaw)
      || !await verify(requester.key, requestSignature, requestPayload(ticket))) throw new Error("Recovery request authorization failed");
  const recipientKey = await importRecipient(recipientRaw);
  if (ticket.recipientFingerprint !== await fingerprint(recipientKey)) throw new Error("Recovery recipient binding failed");
  const accepted = new Set();
  for (const approval of approvals) {
    const actor = approval?.custodian;
    const custodian = custodians.get(actor);
    if (!custodian || custodian.revoked || actor === ticket.requester || actor === ticket.recipient || accepted.has(actor)
        || !bytesOf(approval.signature, 64)
        || !await verify(custodian.key, approval.signature, approvalPayload(ticket, actor))) throw new Error("Independent approval rejected");
    accepted.add(actor);
  }
  if (accepted.size < 2) throw new Error("Approval quorum missing");

  const request = requestDigest(ticket);
  const scope = scopeOf(ticket);
  const target = JSON.stringify(Object.values(scope));
  db.exec("BEGIN IMMEDIATE");
  let committed = false;
  let material;
  let active;
  try {
    active = activeKey();
    if (ticket.keyId !== active.key_id || ticket.epoch !== active.epoch || Date.now() >= ticket.expires) {
      throw new Error("Recovery key epoch or approval expiry invalid");
    }
    const prior = db.prepare("SELECT * FROM cases WHERE id=? OR nonce=? OR target=?").all(ticket.caseId, ticket.nonce, target);
    if (prior.length) {
      if (prior.length !== 1 || prior[0].id !== ticket.caseId || prior[0].request !== request
          || !db.prepare("SELECT 1 FROM outbox WHERE case_id=?").get(ticket.caseId)) throw new Error("Conflicting or incomplete recovery case");
      const result = { suite: SUITE_ID, enc: prior[0].enc, ct: prior[0].ct };
      db.exec("COMMIT");
      committed = true;
      return result;
    }
    failAt("before-unwrap");
    const privateKey = await crypto.subtle.importKey("pkcs8", active.private_der, curve, false, ["deriveBits"]);
    active.private_der.fill(0);
    const recoveryKey = { privateKey, publicKey: await importRecipient(active.public_raw) };
    material = await unwrap(envelope, recoveryKey, { ...scope, kind: "organization", keyId: ticket.keyId, epoch: ticket.epoch });
    failAt("after-unwrap");
    const result = await wrap(material, recipientKey, { ...scope, kind: "device", keyId: ticket.recipientKeyId, epoch: ticket.epoch });
    failAt("after-rewrap");
    if (Date.now() >= ticket.expires) throw new Error("Recovery approval expired before commit");
    db.prepare("INSERT INTO cases VALUES (?,?,?,?,?,?,?)")
      .run(ticket.caseId, ticket.nonce, target, request, result.enc, result.ct, ticket.epoch);
    db.prepare("INSERT INTO outbox VALUES (?,?,?,?,?)")
      .run(ticket.caseId, cfg.tenant, ticket.epoch, JSON.stringify([...accepted].sort()), Date.now());
    db.exec("COMMIT");
    committed = true;
    failAt("after-commit");
    return result;
  } finally {
    material?.fill(0);
    active?.private_der.fill(0);
    if (!committed) db.exec("ROLLBACK");
  }
}

let queue = Promise.resolve();
process.on("message", (message) => {
  // Relay chỉ có quyền gửi yêu cầu. Rotation và dữ liệu outbox nằm ở ranh giới operator fixture.
  queue = queue.then(async () => {
    if (message.kind !== "recover") {
      process.send({ id: message.id, error: "Unsupported authority operation" });
      return;
    }
    try {
      process.send({ id: message.id, result: await recover(message.input) });
    } catch {
      process.send({ id: message.id, error: "Authority denied recovery" });
    }
  });
});
process.on("disconnect", () => { queue.finally(() => db.close()); });
