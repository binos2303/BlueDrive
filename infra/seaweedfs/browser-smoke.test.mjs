import assert from "node:assert/strict";
import test from "node:test";
import { browserTicket } from "./browser-smoke.mjs";

function challenge() {
  return { mode: "runtime", origin: "http://127.0.0.1:3000",
    authorization: { url: "http://s3.localhost:8333/bucket/staging/server?versionId=fixture-version&fixture=a%2Fb" },
    upload_authorization: { method: "PUT", url: "http://s3.localhost:8333/bucket/staging/browser?uploadId=fixture-upload&partNumber=1",
      headers: { "x-amz-meta-test": "fixture" }, body_base64: Buffer.alloc(64, 7).toString("base64") } };
}

test("runtime challenge preserves signed URLs, exact headers and payload", () => {
  const value = challenge();
  const ticket = browserTicket(value);
  assert.equal(ticket.get, value.authorization.url);
  assert.equal(ticket.put, value.upload_authorization.url);
  assert.deepEqual(ticket.headers, value.upload_authorization.headers);
  assert.deepEqual(ticket.payload, Array(64).fill(7));
  assert.equal(ticket.expected_version, "fixture-version");
});

test("runtime challenge rejects latest reads and replayable ordinary PUT", () => {
  for (const change of [
    (value) => { value.authorization.url = "http://s3.localhost:8333/bucket/staging/server"; },
    (value) => { value.upload_authorization.url = "http://s3.localhost:8333/bucket/staging/browser"; },
    (value) => { value.upload_authorization.method = "POST"; },
  ]) {
    const value = challenge();
    change(value);
    assert.throws(() => browserTicket(value));
  }
});

test("runtime challenge rejects external hosts, credentials and unexpected payload", () => {
  for (const change of [
    (value) => { value.authorization.url = "http://outside.invalid/key?versionId=fixture-version"; },
    (value) => { value.authorization.url = "http://test:test@s3.localhost:8333/key?versionId=fixture-version"; },
    (value) => { value.upload_authorization.headers = { Cookie: "fixture=fixture" }; },
    (value) => { value.upload_authorization.body_base64 = Buffer.alloc(63).toString("base64"); },
  ]) {
    const value = challenge();
    change(value);
    assert.throws(() => browserTicket(value));
  }
});

test("legacy browser smoke keeps its checksum receipt contract", () => {
  const value = { origin: "http://localhost:3000", put: "http://s3.localhost:8333/bucket/fixture",
    get: "http://s3.localhost:8333/bucket/fixture", payload: [1, 2], checksum: "fixture-checksum" };
  const ticket = browserTicket(value);
  assert.deepEqual(ticket.headers, { "x-amz-checksum-sha256": value.checksum });
  assert.equal(ticket.get, value.get);
  assert.equal(ticket.put, value.put);
});
