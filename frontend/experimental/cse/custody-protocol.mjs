import { sha256 } from "@noble/hashes/sha2.js";
import { hex, sign } from "./format.mjs";
import { message } from "./trust.mjs";

export const ticketFields = ["caseId", "nonce", "tenant", "workspace", "file", "version", "requester",
  "recipient", "recipientKeyId", "recipientFingerprint", "keyId", "epoch", "expires", "reason", "envelopeDigest"];
export const contentFields = ["tenant", "workspace", "file", "version"];
export const scopeOf = (ticket) => Object.fromEntries(contentFields.map((field) => [field, ticket[field]]));
const digest = (data) => hex(sha256(data));
export const envelopeDigest = (envelope) => digest(message("BlueDrive/recovery/envelope/v1",
  [envelope.suite, hex(envelope.enc), hex(envelope.ct)]));
export const requestPayload = (ticket) => message("BlueDrive/recovery/request/v1", ticketFields.map((field) => ticket[field]));
export const requestDigest = (ticket) => digest(requestPayload(ticket));
export const approvalPayload = (ticket, custodian) => message("BlueDrive/recovery/approval/v1", [requestDigest(ticket), custodian]);
export const signRequest = (ticket, privateKey) => sign(privateKey, requestPayload(ticket));
export const approveRequest = async (ticket, custodian, privateKey) =>
  ({ custodian, signature: await sign(privateKey, approvalPayload(ticket, custodian)) });
