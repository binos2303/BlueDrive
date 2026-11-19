import { sign } from "./format.mjs";
import { unwrap } from "./envelopes.mjs";
import { createKeyBundle, openKeyBundle } from "./recovery.mjs";

const domain = "BlueDrive/device/encrypted-bundle/v1";
export const createDeviceBundle = (identity) => createKeyBundle(identity, domain);

export function deviceSession({ bundle, trustedIdentity, session, requireFreshDevice, idleMs = 60_000, now = Date.now }) {
  if (typeof requireFreshDevice !== "function" || !Number.isSafeInteger(idleMs) || idleMs < 1 || idleMs > 300_000) {
    throw new Error("Device session configuration invalid");
  }
  let generation = 0;
  let active;
  let pending = false;
  let ended = false;
  let timer;

  function lock() {
    generation += 1;
    active = undefined;
    clearTimeout(timer);
  }

  function touch(keys) {
    clearTimeout(timer);
    active = { keys, expires: now() + idleMs };
    timer = setTimeout(lock, idleMs);
    timer.unref?.();
  }

  function unlocked() {
    if (active && now() >= active.expires) lock();
    return active;
  }

  async function withSessionKeys(operation) {
    const keys = unlocked()?.keys;
    if (!keys) throw new Error("Device locked");
    const revision = generation;
    const result = await operation(keys);
    if (revision !== generation || !unlocked()) {
      result.fill(0);
      throw new Error("Device session ended");
    }
    touch(keys);
    return result;
  }

  return {
    status: () => unlocked() ? "UNLOCKED" : "LOCKED",
    lock,
    logout() { ended = true; lock(); },
    async unlock(readOfflineMaterial) {
      if (ended || pending || unlocked()) throw new Error("Device unlock unavailable");
      pending = true;
      const revision = generation;
      let material;
      try {
        await requireFreshDevice(trustedIdentity);
        material = await readOfflineMaterial();
        if (!(material instanceof Uint8Array) || material.length !== 32) throw new Error("Unlock cancelled or material missing");
        const keys = await openKeyBundle(bundle, material, trustedIdentity, session, domain);
        await requireFreshDevice(trustedIdentity);
        if (revision !== generation) throw new Error("Device session ended");
        touch(keys);
      } finally {
        material?.fill?.(0);
        pending = false;
      }
    },
    sign: (payload) => withSessionKeys(({ signer }) => sign(signer, payload)),
    async unwrap(envelope, context) {
      if (context.tenant !== trustedIdentity.tenant || context.keyId !== trustedIdentity.keyId
          || context.epoch !== trustedIdentity.generation || context.kind !== "device") throw new Error("Device envelope scope mismatch");
      return withSessionKeys(({ receive }) => unwrap(envelope, receive, context));
    },
  };
}
