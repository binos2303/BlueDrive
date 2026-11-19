import { sha256 } from "@noble/hashes/sha2.js";
import { bytes, hex, random, sign, verify } from "./format.mjs";
import { importRecipient } from "./envelopes.mjs";
import { fingerprint, message, pinAuthority, verifyEnrollment } from "./trust.mjs";

const windowMs = 30_000;
const skewMs = 2_000;
const maxHistory = 256;
const id = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/;
const hash = /^[0-9a-f]{64}$/;
const digest = (value) => hex(sha256(value));
const checkpointPayload = (row) => message("BlueDrive/directory/checkpoint/v1",
  [row.tenant, row.sequence, row.previous, row.state, row.authority, row.published]);
const checkpointDigest = (row) => digest(checkpointPayload(row));
export const entryPayload = (row) => message("BlueDrive/directory/entry/v1",
  [row.tenant, row.subject, row.device, row.purpose, row.keyId, row.epoch, row.status, row.publicKey]);
const witnessPayload = (row) => message("BlueDrive/directory/witness/v1",
  [row.tenant, row.nonce, row.head, row.issued, row.expires]);
const rotationPayload = (row) => message("BlueDrive/directory/authority-rotation/v1",
  [row.tenant, row.from, row.to, row.sequence, row.previous]);
const entryId = (row) => [row.subject, row.device, row.purpose].join("/");
const stateDigest = (entries) => digest(message("BlueDrive/directory/state/v1", entries.map((row) => digest(entryPayload(row)))));
const positive = (value) => Number.isSafeInteger(value) && value > 0;
const validEntry = (row, tenant) => row.tenant === tenant && [row.subject, row.device, row.keyId].every((value) => id.test(value))
  && ["active", "revoked"].includes(row.status) && ["receive", "sign"].includes(row.purpose)
  && positive(row.epoch) && /^04[0-9a-f]{128}$/.test(row.publicKey);

export async function endorseRotation(tenant, oldKey, newKey, prior) {
  const row = { tenant, from: await fingerprint(oldKey.publicKey), to: await fingerprint(newKey.publicKey),
    sequence: prior.sequence + 1, previous: checkpointDigest(prior) };
  const payload = rotationPayload(row);
  return { ...row, oldSignature: await sign(oldKey.privateKey, payload), newSignature: await sign(newKey.privateKey, payload),
    publicKey: newKey.publicKey };
}

export async function directoryPins(tenant, root, expectedFingerprint, rotations = []) {
  if (!id.test(tenant)) throw new Error("Invalid directory scope");
  const publicKey = await pinAuthority(root, expectedFingerprint);
  const pins = [{ publicKey, id: expectedFingerprint, sequence: 1, previous: null }];
  for (const row of rotations) {
    const old = pins.at(-1);
    const payload = rotationPayload(row);
    if (row.tenant !== tenant || row.from !== old.id || !positive(row.sequence) || row.sequence <= old.sequence
        || !hash.test(row.previous) || row.to !== await fingerprint(row.publicKey)
        || pins.some((pin) => pin.id === row.to)
        || !await verify(old.publicKey, row.oldSignature, payload)
        || !await verify(row.publicKey, row.newSignature, payload)) throw new Error("Authority rotation endorsement invalid");
    pins.push({ publicKey: row.publicKey, id: row.to, sequence: row.sequence, previous: row.previous });
  }
  return Object.freeze(pins.map(Object.freeze));
}

function memoryJournal() {
  const history = [];
  return {
    head: () => history.at(-1),
    links: (after, head) => history.slice(after, head - 1).map((row) => row.checkpoint),
    append(row) {
      if (history.length + 1 !== row.checkpoint.sequence) throw new Error("Concurrent authority publication");
      history.push(row);
    },
  };
}

// Khóa authority đi qua ranh giới operator; journal chỉ lưu checkpoint công khai.
export function directoryAuthority(tenant, root, now = Date.now, journal = memoryJournal()) {
  let keys = root;
  return {
    async publish(rows, nextKey = keys) {
      const current = journal.head();
      const prior = current?.checkpoint;
      if (prior && (prior.tenant !== tenant || prior.authority !== await fingerprint(keys.publicKey))) {
        throw new Error("Authority journal scope or configured key mismatch");
      }
      const entryList = [...rows].sort((a, b) => entryId(a) < entryId(b) ? -1 : entryId(a) > entryId(b) ? 1 : 0);
      if (entryList.length > 256 || entryList.some((row, index) => !validEntry(row, tenant)
          || (index && entryId(entryList[index - 1]) === entryId(row)))) throw new Error("Invalid directory snapshot");
      for (const old of current?.entries ?? []) {
        const row = entryList.find((candidate) => entryId(candidate) === entryId(old));
        if (!row || row.epoch < old.epoch || (row.epoch === old.epoch && digest(entryPayload(row)) !== digest(entryPayload(old)))
            || (old.status === "revoked" && row.status === "active" && old.keyId === row.keyId)) throw new Error("Directory entry transition invalid");
      }
      const entries = await Promise.all(entryList.map(async (row) =>
        ({ ...row, signature: await sign(nextKey.privateKey, entryPayload(row)) })));
      const checkpoint = { tenant, sequence: (prior?.sequence ?? 0) + 1,
        previous: prior ? checkpointDigest(prior) : null, state: stateDigest(entries),
        authority: await fingerprint(nextKey.publicKey), published: now() };
      checkpoint.signature = await sign(nextKey.privateKey, checkpointPayload(checkpoint));
      journal.append({ checkpoint, entries });
      keys = nextKey;
      return structuredClone(checkpoint);
    },
    async latest(request) {
      const currentKeys = keys;
      const { checkpoint, entries } = journal.head() ?? {};
      if (request.tenant !== tenant || !hash.test(request.nonce) || !checkpoint
          || !Number.isSafeInteger(request.after) || request.after < 0 || request.after > checkpoint.sequence
          || (request.after > 0 && checkpoint.sequence - request.after > maxHistory)) throw new Error("Witness request rejected");
      if (checkpoint.tenant !== tenant || checkpoint.authority !== await fingerprint(currentKeys.publicKey)) {
        throw new Error("Authority journal scope or configured key mismatch");
      }
      const links = request.after ? journal.links(request.after, checkpoint.sequence) : [];
      const issued = now();
      const proof = { tenant, nonce: request.nonce, head: checkpointDigest(checkpoint), issued, expires: issued + windowMs };
      proof.signature = await sign(currentKeys.privateKey, witnessPayload(proof));
      const active = journal.head().checkpoint;
      if (checkpointDigest(active) !== proof.head) throw new Error("Witness head advanced");
      return structuredClone({ checkpoint, proof, entries, links });
    },
  };
}

function validSaved(row) {
  return row && positive(row.sequence) && hash.test(row.digest);
}

async function withDeadline(fetchLatest, request) {
  let timer;
  try {
    return await Promise.race([Promise.resolve().then(() => fetchLatest(request)),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Witness unavailable")), 5_000); })]);
  } finally {
    clearTimeout(timer);
  }
}

export function directoryClient({ tenant, pins, store, latest, now = Date.now }) {
  const current = pins.at(-1);
  const pinAt = (sequence) => pins.findLast((pin) => pin.sequence <= sequence);
  async function check(row) {
    const pin = pinAt(row.sequence);
    if (!pin || row.tenant !== tenant || !positive(row.sequence) || !positive(row.published)
        || !hash.test(row.state) || (row.sequence === 1 ? row.previous !== null : !hash.test(row.previous))
        || row.authority !== pin?.id || (row.sequence === pin.sequence && row.previous !== pin.previous)
        || !await verify(pin.publicKey, row.signature, checkpointPayload(row))) throw new Error("Directory checkpoint invalid");
    return checkpointDigest(row);
  }

  async function authorize(expected) {
    if (expected.tenant !== tenant) throw new Error("Directory scope mismatch");
    const before = await store.read(tenant);
    if (before !== undefined && !validSaved(before)) throw new Error("Local checkpoint corrupt");
    const nonce = hex(random(32));
    const requested = now();
    const { checkpoint, proof, entries, links } = await withDeadline(latest, { tenant, nonce, after: before?.sequence ?? 0 });
    const isFresh = (time) => Number.isSafeInteger(proof.issued) && proof.issued >= requested - skewMs
      && proof.issued <= time + skewMs && proof.expires === proof.issued + windowMs && time < proof.expires
      && time >= requested - skewMs;
    const head = await check(checkpoint);
    if (checkpoint.sequence < current.sequence || checkpoint.published > proof.issued + skewMs
        || proof.tenant !== tenant || proof.nonce !== nonce || proof.head !== head || !isFresh(now())
        || !await verify(current.publicKey, proof.signature, witnessPayload(proof))) throw new Error("Witness freshness rejected");
    if (entries.length > 256 || entries.some((row, index) => !validEntry(row, tenant)
        || (index > 0 && entryId(entries[index - 1]) >= entryId(row))) || stateDigest(entries) !== checkpoint.state
        || links.length > maxHistory) throw new Error("Directory state digest mismatch");
    const chain = new Map();
    let previous;
    for (const row of [...links, checkpoint]) {
      if (previous && (row.sequence !== previous.sequence + 1 || row.previous !== previous.digest)) {
        throw new Error("Checkpoint linkage invalid");
      }
      chain.set(row.sequence, row.previous);
      previous = { sequence: row.sequence, digest: row === checkpoint ? head : await check(row) };
    }
    const entry = entries.find((row) => entryId(row) === entryId(expected));
    if (entry && !await verify(current.publicKey, entry.signature, entryPayload(entry))) throw new Error("Directory record signature invalid");
    await store.update(tenant, (saved) => {
      if (!isFresh(now())) throw new Error("Witness freshness expired before commit");
      if (saved !== undefined) {
        if (!validSaved(saved)) throw new Error("Local checkpoint corrupt");
        if (saved.sequence > checkpoint.sequence || (saved.sequence === checkpoint.sequence && saved.digest !== head)
            || (saved.sequence < checkpoint.sequence && chain.get(saved.sequence + 1) !== saved.digest)) {
          throw new Error("Directory rollback or equivocation");
        }
      }
      return { sequence: checkpoint.sequence, digest: head };
    });
    if (!isFresh(now())) throw new Error("Witness freshness expired");
    if (!entry || entry.status !== "active" || (expected.keyId !== undefined && entry.keyId !== expected.keyId)) {
      throw new Error("Device absent, revoked or replaced");
    }
    const raw = bytes(entry.publicKey);
    const publicKey = entry.purpose === "receive" ? await importRecipient(raw)
      : await crypto.subtle.importKey("raw", raw, { name: "ECDSA", namedCurve: "P-256" }, true, ["verify"]);
    if (!isFresh(now())) throw new Error("Witness freshness expired");
    return { entry, publicKey, head: { sequence: checkpoint.sequence, digest: head }, freshnessExpires: proof.expires };
  }

  return {
    authorize,
    async approveEnrollment(expected, enrollment, proof, signature, endorsement) {
      const [domain, realm, subject, device, nonce, expires, receiver, signer] =
        JSON.parse(new TextDecoder().decode(enrollment.payload));
      if (domain !== "p61-device-enrollment" || expected.purpose !== "sign" || realm !== tenant
          || subject !== expected.subject || enrollment.context.tenant !== realm || enrollment.context.workspace !== subject
          || enrollment.context.file !== device || enrollment.context.version !== nonce || !id.test(nonce)
          || enrollment.expires !== expires || !hash.test(receiver) || signer !== await fingerprint(enrollment.signer)) {
        throw new Error("Enrollment scope mismatch");
      }
      const { publicKey, head, freshnessExpires } = await authorize(expected);
      await verifyEnrollment({ ...enrollment, consumed: false }, proof, signature, endorsement, publicKey, now());
      const caseKey = "enrollment/" + tenant + "/" + nonce;
      await store.update(caseKey, (used) => {
        if (used !== undefined || now() >= Math.min(enrollment.expires, freshnessExpires)) throw new Error("Enrollment replay or expiry");
        return head;
      }, { key: tenant, expected: head });
    },
  };
}

export async function browserStore(name) {
  const db = await new Promise((resolve, reject) => {
    const request = indexedDB.open(name, 1);
    request.onupgradeneeded = () => request.result.createObjectStore("trust");
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
    request.onblocked = () => reject(new Error("Trust database blocked"));
  });
  db.onversionchange = () => db.close();
  function operation(key, change, guard) {
    return new Promise((resolve, reject) => {
      const transaction = change ? db.transaction("trust", "readwrite", { durability: "strict" }) : db.transaction("trust", "readonly");
      const store = transaction.objectStore("trust");
      let result;
      let failure;
      transaction.oncomplete = () => resolve(result);
      transaction.onabort = () => reject(failure ?? transaction.error ?? new Error("Trust write aborted"));
      const request = store.get(key);
      request.onsuccess = () => {
        result = request.result;
        if (!change) return;
        function write() {
          try {
            result = change(result);
            store.put(result, key);
          } catch (error) {
            failure = error;
            transaction.abort();
          }
        }
        if (!guard) { write(); return; }
        const check = store.get(guard.key);
        check.onsuccess = () => {
          if (check.result?.sequence !== guard.expected.sequence || check.result?.digest !== guard.expected.digest) {
            failure = new Error("Enrollment authorization became stale");
            transaction.abort();
          } else write();
        };
      };
    });
  }
  return { read: (key) => operation(key), update: (key, change, guard) => operation(key, change, guard), close: () => db.close() };
}
