const start = performance.now();
const key = await crypto.subtle.generateKey({ name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
const input = new Uint8Array(1024 * 1024).fill(0x51);
const params = { name: "AES-GCM", iv: crypto.getRandomValues(new Uint8Array(12)), tagLength: 128 };
const ciphertext = await crypto.subtle.encrypt(params, key, input);
const plain = new Uint8Array(await crypto.subtle.decrypt(params, key, ciphertext));
const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", ciphertext));
postMessage({ verified: plain.length === input.length && plain.every((value) => value === 0x51),
  digest: Array.from(digest).join(","), ms: performance.now() - start });
