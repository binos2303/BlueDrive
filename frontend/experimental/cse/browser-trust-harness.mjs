import assert from "node:assert/strict";
import { directoryAuthority } from "./checkpoints.mjs";
import { publicBytes } from "./envelopes.mjs";
import { hex, signingKey } from "./format.mjs";
import { fingerprint } from "./trust.mjs";

const id = () => crypto.randomUUID();
const onWire = (row) => ({ ...row, signature: [...row.signature] });

export async function browserTrustHarness(context, page, journal) {
  const identity = { tenant: id(), subject: id(), keyId: id(), generation: 1 };
  const registration = await page.evaluate((identity) => globalThis.p615.init(identity), identity);
  let material = registration.material;
  delete registration.material;
  const root = await signingKey();
  const initial = { identity, device: id(), publicKey: hex(await publicBytes(root.publicKey)), pin: await fingerprint(root.publicKey) };
  const row = { ...identity, device: initial.device, publicKey: registration.signer, purpose: "sign", epoch: 1, status: "active" };
  const authority = directoryAuthority(identity.tenant, root, Date.now, journal);
  await authority.publish([row]);
  let delay;

  async function attach(browserContext) {
    await browserContext.exposeBinding("p615Witness", async (source, query) => {
      const result = await authority.latest(query);
      if (delay?.page === source.page) {
        const match = delay;
        delay = undefined;
        match.entered();
        await match.wait;
      }
      return { checkpoint: onWire(result.checkpoint), proof: onWire(result.proof), entries: result.entries.map(onWire),
        links: result.links.map(onWire) };
    });
  }
  await attach(context);
  const run = (target, options = {}) => target.evaluate(({ initial, options }) => globalThis.p615.run(initial, options), {
    initial, options: { ...options, material: options.copied ? undefined : material },
  });
  const observe = (target, reason) =>
    target.evaluate(({ initial, reason }) => globalThis.p615.observe(initial, reason), { initial, reason });
  const first = await run(page, { extra: true });
  assert.equal(first.before, null);
  assert.equal(first.verified, true);

  return {
    attach,
    first,
    async reload(target) {
      const result = await run(target);
      assert.equal(result.before, 1);
      assert.equal(result.verified, true);
      return result;
    },
    async restore(target) {
      // Bản sao profile giữ checkpoint cũ. Witness thực cung cấp head mới từ runner độc lập.
      await authority.publish([row]);
      const result = await run(target, { copied: true });
      assert.equal(result.before, 1);
      assert.equal(result.head, 2);
      assert.equal(result.verified, false);
      return result;
    },
    async restart(browserContext, target) {
      const result = await run(target);
      assert.equal(result.before, 1);
      assert.equal(result.verified, true);
      const faults = await target.evaluate((initial) => globalThis.p615.faults(initial), initial);
      const second = await browserContext.newPage();
      await second.goto(target.url());
      await second.waitForFunction(() => Boolean(globalThis.p615));
      let release;
      const wait = new Promise((resolve) => { release = resolve; });
      const entered = new Promise((resolve) => { delay = { page: target, entered: resolve, wait }; });
      const old = observe(target, "rollback");
      const settledOld = old.then((value) => ({ value }), (error) => ({ error }));
      let timer;
      try {
        await Promise.race([entered, settledOld.then(({ error }) => { throw error ?? new Error("Witness did not pause"); }),
          new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Witness pause timed out")), 4000); })]);
        const revoked = await authority.publish([{ ...row, status: "revoked", epoch: 2 }]);
        assert.equal(await observe(second, "revoked"), revoked.sequence);
        release();
        const verdict = await settledOld;
        if (verdict.error) throw verdict.error;
        assert.equal(verdict.value, revoked.sequence);
        assert.equal(await observe(target, "revoked"), revoked.sequence);
        await target.evaluate(({ initial, material }) => globalThis.p615.revokedUnlock(initial, material), { initial, material });
      } finally {
        clearTimeout(timer);
        release();
        await second.close();
        material = undefined;
      }
      return { ...result, ...faults, conflictingTabs: true, revoked: true };
    },
  };
}
