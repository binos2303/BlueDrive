# SecureDrive MVP API Contract — v1 proposal

> Đối chiếu P0 16/11/2026: kiến trúc đích tại [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md), route/permission matrix hiện có tại [P0 baseline](REFACTOR_P0_BASELINE_2026-11-16.md). SeaweedFS-only, Enterprise My Drive và CSE/recovery không tự biến các contract đề xuất dưới đây thành API đã triển khai. Không đổi route hoặc crypto trong P0.

> Historical baseline note: the contract below describes the pre-tenant API review. The B upload endpoints currently implemented by the repository are unversioned Django routes and are documented in the implementation addendum at the end; this file's proposed `/api/v1` namespace is not an implemented route prefix.

**Status:** v1 remains a contract proposal. Unversioned implementation addenda, including P2 below, describe the repository behavior; they do not implement the proposed versioned namespace.

**Versioned namespace:** `/api/v1`. Existing Django routes remain legacy routes until a separately reviewed migration/compatibility plan is approved.

**Historical review basis:** local `MEDIA_ROOT` ciphertext and server-side AES-GCM. The repository implements a shared S3 adapter, session-authorized multipart uploads, quota reservations, Workspace and admin/audit JSON APIs, and optional presigned downloads. Current multipart objects are published without application AES encryption. See [current architecture](../README.md) and [download implementation](./PRESIGNED_DOWNLOAD_2026-11-07.md); the proposed `/api/v1` endpoints below are not a current route inventory.

## 1. Evidence and scope

Current routes and behavior were checked against:

- [Root URL configuration](../backend/securedrive/urls.py)
- [Account URLs](../backend/accounts/urls.py), [account views](../backend/accounts/views.py), [account API views](../backend/accounts/api_views.py), [registration forms](../backend/accounts/forms.py)
- [Dashboard URLs](../backend/dashboard/urls.py), [dashboard views](../backend/dashboard/views.py)
- [File URLs](../backend/files/urls.py), [file views](../backend/files/views.py), [file forms](../backend/files/forms.py), [file validators](../backend/files/validators.py), [File model](../backend/files/models.py)
- [Folder URLs](../backend/folders/urls.py), [folder views](../backend/folders/views.py), [folder forms](../backend/folders/forms.py), [Folder model](../backend/folders/models.py)
- [Sharing URLs](../backend/sharing/urls.py), [sharing views](../backend/sharing/views.py), [sharing permissions](../backend/sharing/services.py), [Share model](../backend/sharing/models.py)
- [ActivityLog model](../backend/logs/models.py), [audit helper](../backend/logs/services.py)
- [Django settings](../backend/securedrive/settings.py), [account tests](../backend/accounts/tests.py), [dashboard tests](../backend/dashboard/tests.py)

The current authorization implementation scopes owned files and folders by `owner=request.user`; sharing adds `viewer`/`editor` access resolved server-side. It does not yet model business tenants. API v1 must derive user, tenant, roles, ownership, quota and storage placement on the server. A request-supplied `owner_id`, `tenant_id`, `bucket`, `object_key` or storage credential is never authoritative.

## 2. Proposed common API rules

### 2.1 Authentication, CSRF and transport

- Require HTTPS in deployed environments.
- Use the existing Django session as the initial authentication mechanism. Browser requests use `credentials: "include"`.
- Require a valid CSRF token for unsafe session-authenticated methods (`POST`, `PATCH`, `PUT`, `DELETE`), including anonymous registration/login. The `GET /accounts/api/csrf/` route bootstraps the token.
- `401 unauthenticated` is the proposed v1 JSON behavior. Do not redirect API requests to an HTML login page.
- Public registration and login should be rate-limited before v1 release; the current unversioned endpoints do not have an application-level rate limiter. Login failures use the same response for unknown/ambiguous email and bad password. Registration conflicts use a generic response for duplicate username/email.
- Session rotation on login and session invalidation on logout are mandatory.
- The auth UI obtains account context from `/accounts/api/me/` after successful login/registration; the endpoint derives active tenant memberships, roles, and account type from Django records. Multiple active business memberships are returned as a list without silently selecting one.

### 2.2 Stable JSON error envelope

All v1 JSON errors use this shape. Do not return stack traces, SQL errors, filesystem paths, object keys, credentials, encryption keys, or provider responses.

```json
{
  "error": {
    "code": "validation_error",
    "message": "One or more fields are invalid.",
    "field_errors": {
      "name": ["This field is required."]
    },
    "request_id": "req_01J..."
  }
}
```

`field_errors` is omitted when not applicable. `request_id` is a non-secret correlation identifier; detailed exceptions remain server-side and must be redacted. Error codes below are stable machine-readable identifiers; message text may be localized.

| HTTP | When to use | Example codes |
|---|---|---|
| `400` | Malformed JSON, invalid fields, unsupported operation | `invalid_request`, `validation_error`, `invalid_cursor` |
| `401` | No valid authenticated session | `unauthenticated` |
| `403` | Authenticated but lacks an explicit role/capability | `permission_denied`, `admin_required`, `tenant_admin_required` |
| `404` | Resource absent **or not visible to this principal** | `not_found` |
| `409` | State/name conflict, stale version, non-repeatable transition | `name_conflict`, `invalid_state`, `idempotency_conflict` |
| `413` | Request/file exceeds configured size/batch limit | `payload_too_large`, `batch_too_large` |
| `415` | Unsupported content type | `unsupported_media_type` |
| `422` | Request is syntactically valid but violates operation-specific semantic rules | `invalid_destination`, `unsupported_file_type`, `integrity_failed` |
| `429` | Rate limit reached | `rate_limited` |
| `500` | Unexpected server failure; generic message only | `internal_error` |
| `503` | Required storage/scanning dependency unavailable | `service_unavailable` |

To prevent resource enumeration, file/folder reads and mutations return the same `404 not_found` for a missing resource and a resource not owned/shared with the caller. Return `403` only when the resource is visible but the caller lacks the operation capability and revealing its existence is allowed by product policy. Never accept a client-selected tenant or owner as a substitute for authorization.

### 2.3 Pagination and idempotency

- List endpoints use cursor pagination: `limit` defaults to `50`, allowed range `1..100`; `cursor` is opaque and bound to the authenticated principal, query filters and sort. Response: `items`, `page.next_cursor` and `page.has_more`.
- Cursors must not encode secrets or permit changing tenant/scope. Invalid, expired or query-mismatched cursors return `400 invalid_cursor`.
- For creation or state-changing requests that a client may retry after a network timeout, accept `Idempotency-Key` (opaque client-generated value, bounded length). Scope keys to authenticated actor + route + normalized request body. Same key and same body returns the original status/body; same key with a different body returns `409 idempotency_conflict`.
- Idempotency retention duration and backend persistence are open decisions (see §6). Until implemented, clients must not assume retry-safe behavior.

Per-endpoint policy proposed for v1:

| Endpoint(s) | Idempotency behavior |
|---|---|
| `GET` endpoints, including listings, upload status, quota and audit search | No key; safe reads. |
| `POST /auth/register`, `POST /folders`, `POST /uploads`, upload complete/abort, all copy operations, and admin suspend/restore/delete | Require `Idempotency-Key`; same key/body replays the original result. A different body for the same key is `409 idempotency_conflict`. |
| `POST /auth/login`, `POST /auth/logout`, `POST .../download-authorizations` | No key in the initial contract. Login/logout are session operations; download authorization should be read-only/short-lived and must not mutate file state. Repeated logout is proposed to return `204`. |
| `PATCH` rename/profile/settings and `POST` move/trash/restore | Naturally state-targeting; same requested target/state should return the current representation without duplicating side effects. If implementation uses asynchronous side effects, also require a key. |
| `POST /me/password` | Do not retry automatically after an ambiguous network failure; require fresh authentication/current password before another attempt. |
| `PUT /uploads/{id}/content` or per-part direct upload | Bind bytes/checksum to the upload ID and part number. A repeat with identical checksum is safe; a repeat with different bytes is `409 idempotency_conflict`. |

The implementation must persist idempotency records transactionally with the operation where possible; the matrix is a contract proposal, not a claim that current routes provide retry safety.

### 2.4 Proposed common resource shapes

```json
{
  "id": "file_opaque_id",
  "type": "file",
  "name": "report.pdf",
  "parent_id": "folder_opaque_id",
  "size_bytes": 12345,
  "mime_type": "application/pdf",
  "state": "available",
  "created_at": "2026-01-01T12:00:00Z",
  "updated_at": "2026-01-01T12:30:00Z"
}
```

`parent_id: null` means the caller's Drive root. `state` is server-owned; proposed values are `uploading`, `verifying`, `scanning`, `available`, `failed`, `trashed`. Do not expose storage paths, encryption keys/nonces, wrapped keys, bucket names or object keys.

## 3. Existing routes: observed behavior, not v1 JSON guarantees

Most current Drive/account routes are HTML views with redirects and Django messages, not stable JSON APIs. Except for the three JSON account API routes below, do not build a typed frontend API client against their HTML responses as though they were JSON.

| Existing route | Method(s) | Auth/scope and observed behavior | Status/validation/audit evidence |
|---|---|---|---|
| `/accounts/register/` | `GET`, `POST` | Public Django registration form. Uses `RegisterForm` (`username`, `email`, `password1`, `password2`); authenticated users redirect to dashboard. | Invalid form re-renders HTML; success creates user, logs in and redirects. No JSON error contract or registration audit event found. |
| `/accounts/login/` | `GET`, `POST` | Public Django login form; username/password authentication. | Invalid credentials render HTML message; success logs `LOGIN` and redirects (staff to Django admin). No JSON login response/rate-limit behavior evidenced in the view. |
| `/accounts/logout/` | `POST` | Authenticated, CSRF-protected Django session logout. | GET is `405` after the current `require_POST` change; success logs `LOGOUT`, flushes the session, redirects. |
| `/accounts/profile/` | `GET`, `POST` | Authenticated HTML page; POST action `update_email` or `change_password`. Email form validates email; Django `PasswordChangeForm` validates password. | Success/error use messages/redirect; profile changes do not currently create explicit activity events. |
| `/accounts/api/csrf/` | `GET` | Public DRF route. | `200 {"csrfToken":"..."}`; ensures CSRF cookie; no persistent state. |
| `/accounts/api/register/` | `POST` | Public JSON endpoint; explicit Django CSRF protection; accepts `username`, `email`, `password1`, `password2`. Creates a user but does not establish a session. | `202` with the same generic detail for accepted new registrations and duplicate username/email; invalid fields return `400` with `fieldErrors`. The user must sign in afterwards. No registration audit event or rate limiter yet. |
| `/accounts/api/login/` | `POST` | Public JSON endpoint; explicit Django CSRF protection; authenticates by email through Django's configured backend. Calls Django `login()` to rotate/create the session. | `200 {"authenticated":true}`; malformed email returns `400`; bad password, unknown email, or ambiguous duplicate email return the same `401` detail. Successful login writes `LOGIN`; no rate limiter yet. |
| `/accounts/api/me/` | `GET`, `PATCH` | DRF `SessionAuthentication` + `IsAuthenticated`. Reads current Django user from session. PATCH accepts only `{"email":"..."}`. | Returns profile, active tenant context and memberships derived from backend records; `account.type` is `individual`, `business` or `unclassified`. For multiple business memberships, `account.tenant` is null and all memberships are returned, without choosing an active tenant. Invalid email returns `400 fieldErrors`; unknown fields return `400 detail`. Anonymous/expired sessions are rejected (DRF session auth can return `403`). |
| `/accounts/api/logout/` | `POST` | DRF session auth; accepts no meaningful body; logs `LOGOUT` and calls Django logout. | Success `204` with no JSON body; authentication/CSRF response is not yet normalized to v1 envelope. |
| `/` | `GET` | Authenticated dashboard HTML; lists live root folders/files owned by user. Supports `sort=name|modified|size|type`, `direction=asc|desc`. | `login_required` redirect for browser; no pagination or JSON schema. |
| `/drive/folder/{folder_id}/` | `GET` | Authenticated folder HTML; owner or effective share recipient; lists live children and logs `VIEW`. | Inaccessible/missing folder is `404`; sorting only, no pagination. |
| `/drive/recent/`, `/drive/search/` | `GET` | Authenticated HTML. Recent is capped at 50 per resource kind; search is owner-scoped and capped at 50 files and 50 folders. | No JSON response contract. |
| `/drive/create-folder/` | `POST` | Authenticated HTML form. Optional `parent` is resolved and authorized server-side; owner is set by server. Name is trimmed, required, max 255; duplicate live sibling names are rejected case-insensitively. | Redirect + message, not JSON; logs `CREATE_FOLDER`. |
| `/drive/upload/` | `POST` | Authenticated multipart upload (`file_path[]`, optional `folder`/`folder_id`). Server validates allowed type/content, filename, MIME, SHA-256 and max `100 MiB`, encrypts on server, stores ciphertext under Django `MEDIA_ROOT`. | Redirect + messages; per-file upload and encryption audit events on success. No upload session or resumability. |
| `/drive/folder-upload/` | `POST` | Authenticated multipart directory upload (`files[]`, `relative_paths[]`, optional `parent`). | Redirect/messages; not an upload-session API; server currently accepts client relative paths after normalization and folder tree creation. |
| `/drive/files/{id}/details/`, `/drive/folder/{id}/details/` | `GET` | Authenticated JSON detail endpoints; owner or share-aware visibility checks. File details include name, owner username, size, MIME, timestamps, location, encryption flag, access/permission, last activity, hash. Folder details return folder metadata. | `JsonResponse`; missing/inaccessible object is `404`. Existing shape uses formatted timestamps and is not versioned. |
| `/drive/files/{id}/view/`, `/drive/files/{id}/download/` | `GET` | Authenticated owner or share recipient; server checks access, decrypts, integrity-checks and streams file. Download logs `DOWNLOAD`/`DECRYPT`; view logs `VIEW`. | Binary response; unauthorized/inaccessible file is `404`; decryption/integrity failures use messages + redirect, not stable JSON. |
| `/drive/files/{id}/rename/`, `/files/{id}/move/`, `/files/{id}/copy/`, `/file/{id}/cut/` | `POST` | Authenticated; owner/editor checks. Rename validates filename/extension and duplicate; move validates destination scope and duplicate; copy/cut currently use session clipboard behavior. | Redirect + messages. Successful rename/move/copy/cut have corresponding activity actions. |
| `/drive/files/{id}/trash/`, `/drive/files/{id}/restore/` | `POST` | Owner-scoped file soft delete/restore. Restore checks parent-folder state and name conflict. | Redirect + messages; logs `DELETE` / `RESTORE`. |
| `/drive/files/{id}/delete/` | `POST` | Owner-scoped permanent deletion of a trashed file. | Redirect + messages; logs `PERMANENT_DELETE`. |
| `/folder/{id}/rename/`, `/folder/{id}/delete/`, `/folder/{id}/restore/`, `/folder/{id}/delete-permanently/` | `POST` | Folder mutations; operations are owner-scoped except rename can use share-aware edit checks. Folder trash/restore affects subtree. | Redirect + messages; logs rename/delete/restore/permanent delete. |
| `/drive/trash/`, `/drive/trash/bulk-action/` | `GET`, `POST` | Authenticated owner trash HTML; bulk action accepts file/folder IDs and `restore` or `permanent_delete`. | Redirect/messages; no JSON atomic batch contract. |
| `/files/{id}/copy/`, `/files/{id}/move/`, `/files/paste/`, `/folders/{id}/copy/`, `/folders/{id}/cut/`, `/folders/paste/`, `/drive/bulk-action/`, `/drive/bulk-paste/` | `POST` | Authenticated legacy clipboard/bulk HTML actions; permissions are checked server-side. | Redirect/messages; request/session semantics are legacy, not a stable API. |
| `/admin/` | `GET` and Django admin methods | Built-in Django admin, protected by Django staff/superuser permissions. | Not a custom JSON user-management or audit-search API. |

**Registration limitation:** the current Django user email column is not unique at the database level. The endpoint checks duplicate addresses case-insensitively and responds generically, but concurrent or alternate-path registration can still create duplicate email rows. Before public SaaS exposure, audit existing duplicates and add a reviewed normalized-email uniqueness strategy; login rejects ambiguous email matches rather than choosing an account.

Current activity event vocabulary is defined by `ActivityLog.Action`: `LOGIN`, `LOGOUT`, `UPLOAD`, `DOWNLOAD`, `VIEW`, `COPY`, `CUT`, `MOVE`, `RENAME`, `DELETE`, `RESTORE`, `PERMANENT_DELETE`, `CREATE_FOLDER`, `ENCRYPT`, `DECRYPT`, `SHARE`, `REVOKE_SHARE`. Coverage is not complete for all state changes (for example profile email/password updates and admin user changes).

## 4. Proposed `/api/v1` endpoint contracts

The following JSON contracts are proposed for MVP implementation. Fields named as server-derived are never accepted as authority from the client. Common errors and pagination follow §2.

### 4.1 Registration, login, logout, current user and profile

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `POST /api/v1/auth/register` | Public; rate-limited. Creates an individual account only if that is the approved MVP rule; do not allow client to set role/type/tenant. | `{"username":"...","email":"...","password":"...","password_confirm":"..."}` | `201 {"user":{"id":"...","username":"...","email":"..."},"session":{"authenticated":true}}` | `400 validation_error` (required fields, email, username, password policy/mismatch); `409 username_or_email_unavailable` (use non-enumerating policy if email uniqueness is sensitive); `429 rate_limited`. Rotate session identifier after success. | Proposed `REGISTER`; test validation, duplicates, no privilege fields accepted, session rotation, CSRF/rate limit. Existing registration is HTML and currently has no registration audit event. |
| `POST /api/v1/auth/login` | Public; rate-limited. | `{"username":"...","password":"..."}` | `200 {"user":{"id":"...","username":"..."},"session":{"authenticated":true}}` | `400 validation_error`; `401 invalid_credentials` (same response for unknown user/wrong password/inactive account); `429 rate_limited`. Rotate session on success. | Existing `LOGIN`; test valid/invalid/inactive, generic error, rate limiting, session fixation. |
| `POST /api/v1/auth/logout` | Authenticated session; CSRF required. | Empty JSON `{}`. | `204` no body; session invalidated. | `401 unauthenticated`; `403 csrf_failed`. Repeated logout may return `204` to make client cleanup safe (confirm implementation policy). | Existing `LOGOUT`; test session cannot access protected route afterward and CSRF required. |
| `GET /api/v1/me` | Authenticated user; data limited to self. | None. | `200 {"user":{"id":"...","username":"...","email":"..."},"account":{"type":"unclassified","tenant":null,"upgrade_eligible":null}}` until the backend has real account/tenant records. | `401 unauthenticated`. Never infer account type from email or route. | No mutation event. Test user isolation and explicit `unclassified`; response shape must not synthesize tenant/quota. Current equivalent is unversioned `GET /accounts/api/me/`. |
| `PATCH /api/v1/me/profile` | Authenticated; self only. | `{"email":"new@example.com"}`. Reject unknown fields. | `200 {"user":{"id":"...","username":"...","email":"new@example.com"}}` | `400 validation_error`; `401`; `409 email_unavailable` only if unique email is adopted. Username remains read-only unless separately approved. | Proposed `PROFILE_UPDATED`; test invalid/extra fields, persistence, cannot change username/role/owner. Existing unversioned `PATCH /accounts/api/me/` updates email only and has no profile audit event. |
| `POST /api/v1/me/password` | Authenticated; self only; CSRF required. | `{"current_password":"...","new_password":"...","new_password_confirm":"..."}`. Never echo password fields. | `204` no body. Preserve current session or require re-login according to approved session policy; revoke other sessions if session inventory is implemented. | `400 validation_error` (wrong current password, confirmation mismatch, Django password validators); `401`; `403 csrf_failed`. Generic safe messages only. | Proposed `PASSWORD_CHANGED`; test current-password check, validators, confirmation, session behavior, no password in response/log, other sessions invalidated per policy. Existing HTML profile uses Django `PasswordChangeForm` and `update_session_auth_hash`; no JSON password endpoint/audit event exists. |
| `GET /api/v1/me/settings` | Authenticated; self only. | None. | `200 {"settings":{}}` until concrete settings are approved and implemented. | `401`. Do not expose inactive/cosmetic settings. | No mutation event. Test no unsupported fields are emitted. **Open:** whether to omit this endpoint entirely until there is a real setting. |
| `PATCH /api/v1/me/settings` | Authenticated; self only. | Only an allowlisted, versioned set of implemented setting fields; initial MVP contract has no writable fields. | No success response until a real setting is selected. | Proposed `400 unsupported_setting` for any unimplemented key; do not return a success-shaped no-op. | Proposed `SETTINGS_UPDATED`; tests for allowlist and persistence required before adding fields. **Open:** settings scope. |

### 4.2 Drive listings and folder creation

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `GET /api/v1/drive/items` | Authenticated user. Default scope is the caller's owned Drive; shared resources require effective share access and should use a separately explicit scope. | Query: `parent_id` (opaque folder ID or omitted for root), `scope=owned|shared` (if shared listing is approved), `sort=name|modified|size|type`, `direction=asc|desc`, `limit`, `cursor`. | `200 {"items":[{"id":"...","type":"file|folder","name":"...","parent_id":"...","size_bytes":123,"mime_type":"...","state":"available","updated_at":"..."}],"page":{"next_cursor":null,"has_more":false}}` | `400 invalid_request|invalid_cursor`; `401`; inaccessible `parent_id` returns `404 not_found`; unsupported sort/direction returns `400`. Exclude trashed items by default. | Read audit policy is open; current views log `VIEW` when opening a folder, not for every list. Tests: owner isolation, shared visibility, trashed filtering, cursor stability, sort, max limit, no cross-account leakage. Current `/` and `/drive/folder/{id}/` return HTML, no pagination. |
| `POST /api/v1/folders` | Authenticated; create in caller-owned live parent. Shared Editor may create only where existing share rules allow, if that capability is retained. | `{"name":"Reports","parent_id":null}`. No `owner_id` or tenant field. | `201 {"item":{"id":"...","type":"folder","name":"Reports","parent_id":null,"state":"available","created_at":"..."}}` | `400 validation_error` (blank/name >255/invalid characters per approved folder policy); `401`; `404 invalid/inaccessible parent`; `409 name_conflict`. Parent and owner are resolved on server. | Existing `CREATE_FOLDER`; test root/nested scope, viewer denial, duplicate case-insensitive name, deleted/inaccessible parent, no caller-selected owner. Current `/drive/create-folder/` is a POST HTML form. |

### 4.3 Upload session and optional direct-upload URLs

The existing implementation accepts complete multipart bodies at `/drive/upload/`, validates and hashes plaintext, encrypts server-side using AES-GCM, then stores ciphertext in `MEDIA_ROOT`. It has no resumable session or object-store protocol.

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `POST /api/v1/uploads` | Authenticated; create only in caller-owned live parent or explicitly editable share destination. | `{"name":"report.pdf","size_bytes":12345,"mime_type":"application/pdf","sha256":"hex-or-null","parent_id":null}`. Never accept storage location, bucket, object key, tenant or owner. | `201 {"upload_id":"...","state":"uploading","part_size_bytes":4194304,"max_size_bytes":104857600,"expires_at":"...","transport":"api_multipart"}`. File is not listed as available yet. | `400 validation_error`; `401`; `404 parent not found/inaccessible`; `413 payload_too_large`; `415 unsupported_media_type`; `409 name_conflict` only if product chooses reject-on-conflict; `429`. | Proposed `UPLOAD_INITIATED`; test size/type/name, parent authorization, quota reservation race, hidden upload from normal listing, idempotency. |
| `PUT /api/v1/uploads/{upload_id}/content` | Authenticated owner of that upload session; session must be live. | `multipart/form-data` with one `file` (initial simple server-streamed option), or a documented chunk format. The server binds file bytes to session metadata; no client storage identifiers. | `202 {"upload_id":"...","state":"verifying"}` after bytes accepted; not yet `available`. | `400 invalid_state|validation_error`; `401`; `404` for absent/other-user session; `409 invalid_state`; `413`; `415`; `422 unsupported_file_type|integrity_failed`; `503 service_unavailable`. | `UPLOAD`; later `ENCRYPT`; test bounded memory/body, MIME/signature, extension, hash, encryption, quota, cleanup on partial failure, no premature availability. Existing `/drive/upload/` performs full upload synchronously and redirects. |
| `GET /api/v1/uploads/{upload_id}` | Authenticated owner of upload. | None. | `200 {"upload_id":"...","state":"uploading|verifying|scanning|completed|failed|canceled","received_bytes":123,"total_bytes":456,"retryable":false,"error":{"code":"...","message":"..."},"file_id":"..."}`. `file_id` only when completed and available. Omit unmeasurable progress. | `401`; `404` absent/other user's session. | No extra event for poll. Test owner isolation and server-truth state/progress. **Optional if upload is single-request and state can be returned from complete.** |
| `POST /api/v1/uploads/{upload_id}/complete` | Authenticated owner; only after all required bytes/parts received. | `{"sha256":"...","parts":[{"part_number":1,"checksum":"..."}]}` only if chunking is selected; otherwise `{}`. | `202 {"upload_id":"...","state":"verifying"}`. Later state becomes `scanning` if scanning is enabled, then `completed` only after backend confirms integrity and mandatory checks; item becomes visible/downloadable then. | `400 validation_error`; `401`; `404`; `409 invalid_state|incomplete_upload`; `422 integrity_failed`; `503`. | Proposed `UPLOAD_COMPLETED` only after terminal successful checks; tests for incomplete parts, replay, checksum mismatch, scan pending/reject, no early listing/download. |
| `POST /api/v1/uploads/{upload_id}/abort` | Authenticated owner; live session. | `{}`. | `200 {"upload_id":"...","state":"canceled"}`; idempotent repeat returns same terminal state. | `401`; `404`; `409 invalid_state` if already committed/available. | Proposed `UPLOAD_ABORTED`; test repeated abort, cleanup, quota release, cannot abort another user session. |

#### Optional direct-to-object-storage variant — not selected

If a later architecture decision selects direct upload, replace `/content` transport with:

- `POST /api/v1/uploads/{upload_id}/parts/{part_number}/authorization` → `200 {"url":"<short-lived bearer URL>","method":"PUT","headers":{},"expires_at":"..."}`.
- The server, not the client, chooses provider, bucket, object key, part number bounds, content constraints, expiry and tenant placement. The returned signed URL is a credential: send only over TLS, do not log, persist in analytics, or include in error messages.
- Completion must verify uploaded part checksums/size from trusted provider metadata before state transition.

This variant is **not compatible by default** with current server-side encryption: direct plaintext upload to the final object bypasses the existing server encryption pipeline. Decide between server-proxied encryption, client-side encryption/key management, or an explicitly designed encrypted staging flow before adopting presigned URLs. Never permit the client to choose a bucket or object key. Direct upload tests must include URL scope/expiry, replay, wrong-part, checksum mismatch, unauthorized tenant/object, provider failure, and no availability before verification/scanning.

### 4.4 Download authorization

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `POST /api/v1/files/{file_id}/download-authorizations` | Authenticated owner or user with effective `viewer`/`editor` share. CSRF required for session auth. | `{}`. | Preferred with current local storage: `200` streaming body with safe `Content-Disposition`, `Content-Length`, `X-Content-Type-Options: nosniff`. If future object storage is approved: `200 {"download_url":"...","expires_at":"..."}` with short-lived, read-only authorization. | `401`; `404 not_found` for missing, trashed, deleted-parent or unauthorized file; `422 integrity_failed`; `503` storage unavailable. | Existing `DOWNLOAD` + `DECRYPT`; tests owner/share viewer/editor, revoked share, trashed resource, wrong user gets indistinguishable 404, integrity failure never serves bytes, signed URL expiry if applicable. Existing equivalent is `GET /drive/files/{id}/download/`. |

### 4.5 Rename, move, copy, trash and restore

All target IDs are resolved and permission-checked server-side. A tenant/user supplied in JSON does not change the scope. Name collision policy for these v1 operations is **reject with `409 name_conflict`** (consistent with existing move/restore behavior); no silent overwrite or auto-rename.

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `PATCH /api/v1/files/{id}` | Owner or effective share Editor. | `{"name":"report-final.pdf"}` only; preserve current rule that extension cannot change. | `200 {"item":{...updated file...}}` | `400 validation_error`; `401`; `404` missing/inaccessible/trashed; `409 name_conflict`; `422 invalid_filename|extension_change`. | Existing `RENAME`; test filename validation, extension policy, duplicate case-insensitive, viewer forbidden, same-owner scope. |
| `PATCH /api/v1/folders/{id}` | Owner or effective share Editor. | `{"name":"Reports 2026"}` only. | `200 {"item":{...updated folder...}}` | `400`; `401`; `404`; `409 name_conflict`. | Existing `RENAME`; test root/nested, duplicate, shared permissions, subtree path/visibility. |
| `POST /api/v1/files/{id}/move` | Owner or Editor. | `{"parent_id":"folder_id"}`; `null` means My Drive root for owner. | `200 {"item":{...updated file...}}` | `400`; `401`; `404` source/destination inaccessible; `409 name_conflict|invalid_state`; `422 invalid_destination`. A shared Editor cannot move a resource outside the authorized share boundary or to personal root. | Existing `MOVE`; test cross-user/tenant rejection, deleted destination, same folder, duplicate, share boundary. |
| `POST /api/v1/folders/{id}/move` | Owner or Editor for the complete subtree. | `{"parent_id":"folder_id"}`; root only where caller owns source/destination. | `200 {"item":{...updated folder...}}` | `400`; `401`; `404`; `409 name_conflict|invalid_state`; `422 invalid_destination` including move into itself/descendant. | Existing folder paste/move functionality is legacy/session based; test cycles, complete subtree permissions, duplicate, cross-scope denial, atomicity. |
| `POST /api/v1/files/{id}/copy` | Owner or Editor. | `{"parent_id":"folder_id"}`; optional `name` only if product wants explicit target naming. | `201 {"item":{...new file...}}` | `400`; `401`; `404`; `409 name_conflict`; `422 invalid_state`; `503` if decrypt/re-encrypt/storage fails. Copy must use server-generated identity/storage path and fresh encryption material as required by the current clone service. | Existing `COPY`; test source/destination access, ciphertext integrity, fresh file ID/DEK/nonce, quota accounting, cleanup on failure. |
| `POST /api/v1/folders/{id}/copy` | Owner or Editor for entire source subtree. | `{"parent_id":"folder_id","name":null}` optional name only by explicit approval. | `201 {"item":{...new folder...},"copied_counts":{"files":0,"folders":1}}` | `400`; `401`; `404`; `409 name_conflict`; `422 invalid_destination` (self/descendant); `503` partial storage/decryption failure. Atomicity/partial result behavior must be decided before implementation. | Existing folder copy service is legacy; test subtree permission, cycles, files/encryption copied, quota, rollback/cleanup. |
| `POST /api/v1/drive/items/{type}/{id}/trash` | Owner; share Editor only if product explicitly permits moving owner content to trash (current semantics are owner-only for delete). | `{}`. | `200 {"item_id":"...","state":"trashed","trashed_at":"..."}`. Folder trash recursively marks live descendants; it does not permanently delete. | `401`; `404`; `409 invalid_state`; `403 permission_denied` if visible but not owner. | Existing `DELETE`; test soft-delete subtree consistency, shared access removal, repeat behavior, no storage bytes removed. |
| `POST /api/v1/drive/items/{type}/{id}/restore` | Owner only. | `{}`; destination remains original parent in MVP. | `200 {"item":{...,"state":"available"}}`. | `401`; `404`; `409 name_conflict|parent_in_trash|invalid_state`; no automatic overwrite. | Existing `RESTORE`; test parent restoration order, duplicate conflict, folder subtree, resources from another owner hidden. |
| `DELETE /api/v1/drive/items/{type}/{id}` | Owner only; item must be in Trash. | No body. | `204` after irreversible deletion and storage cleanup is confirmed. | `401`; `404`; `409 item_not_trashed`; `503` if cleanup cannot safely complete. | Existing `PERMANENT_DELETE`; mandatory tests for confirmation state, subtree behavior, storage cleanup failure/retry, audit retained after deletion. **Open:** immediate purge vs retention/deferred purge and whether folders are allowed in one operation. |

`{type}` is exactly `files` or `folders`; reject other values. If a generic ID namespace is not implemented, use separate file/folder routes rather than guessing resource type.

### 4.6 Quota usage

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `GET /api/v1/quota/usage` | Authenticated user. Server derives individual account or tenant membership. | None. | Proposed `200 {"scope":{"type":"individual|business|unclassified","tenant_id":null},"used_bytes":123,"reserved_bytes":0,"limit_bytes":null,"available_bytes":null,"as_of":"..."}`. Return `null` limit/available while classification/limit is genuinely unknown; never invent quota. | `401`; `404` only if no usage subject can be resolved; `503` if authoritative accounting is temporarily unavailable. | No existing quota model/endpoint/event. Tests concurrent reservation, include/exclude trash policy, tenant aggregation/member allocation, null/unclassified response, cannot select another tenant. **Open:** whether usage includes trashed objects, replicas, pending uploads and shared files. |

### 4.7 Admin user lifecycle and audit search

The repository has Django `/admin/` with staff/superuser policy and now has `Tenant`/`Membership` records. It has no global admin JSON APIs or audit-search endpoint. The two tenant-membership lifecycle endpoints below are implemented under the unversioned accounts API; they are not the proposed global site-admin user-suspension APIs.

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `GET /api/v1/admin/users` | Authenticated Django staff/site admin; global user scope. Future Tenant Admin must be tenant-scoped server-side. | Query: `search`, `status=active|suspended`, `limit`, `cursor`, approved stable sort. | `200 {"items":[{"id":"...","username":"...","email":"...","status":"active","created_at":"..."}],"page":{...}}`; never return password/hash/session/secret fields. | `401`; `403 admin_required`; `400 invalid_cursor`. | Read audit requirement/open. Test nonstaff denial, page/search filters, no credentials, tenant boundary. |
| `POST /api/v1/admin/users/{id}/suspend` | Site admin; cannot suspend self or last active superuser absent approved break-glass workflow. | `{"reason":"..."} `; reason bounded and must not contain credentials/secrets. | `200 {"user":{"id":"...","status":"suspended"}}`; invalidate target sessions. | `400 validation_error`; `401`; `403 admin_required`; `404`; `409 invalid_state|last_admin_protected`. | Proposed `USER_SUSPENDED`; test role, self/last-admin, session invalidation, idempotency and audit actor/target. |
| `POST /api/v1/admin/users/{id}/restore` | Site admin; restore/reactivate only an eligible suspended account. | `{"reason":"..."}` optional if policy permits. | `200 {"user":{"id":"...","status":"active"}}`. | `400`; `401`; `403`; `404`; `409 invalid_state`. | Proposed `USER_RESTORED`; test inactive/suspended distinction, sessions remain invalidated (require fresh login), actor audit. |
| `DELETE /api/v1/admin/users/{id}` | Site admin; re-authentication/step-up recommended. **Proposed behavior is tombstone/deactivation**, not immediate cascade deletion, pending retention decision. | No body or optional `{"reason":"..."}`; must never accept owner/tenant reassignment from caller. | Proposed `202 {"user":{"id":"...","status":"deletion_pending"}}` if retention workflow selected; otherwise `204` only after defined deletion semantics complete. | `401`; `403`; `404`; `409 protected_admin|deletion_blocked`; `202` if asynchronous. | Proposed `USER_DELETION_REQUESTED` and terminal `USER_DELETED`; tests ownership/data retention, login/session invalidation, audit retention, retry and last-admin protections. **Open:** hard delete vs anonymize vs deactivate; handling of files, shares, logs and billing. |
| `GET /api/v1/admin/audit-events` | Site admin; future Tenant Admin limited to own tenant events, with tenant derived server-side. | Query: `actor_id`, `action`, `resource_type`, `resource_id`, `created_after`, `created_before`, `limit`, `cursor`. Search is bounded by time window and page size. | `200 {"items":[{"id":"...","actor":{"id":"..."},"action":"UPLOAD","resource":{"type":"file","id":"..."},"created_at":"...","request_id":"...","summary":"..."}],"page":{...}}`. No file content, secrets, raw storage path or unrestricted descriptions. | `401`; `403 admin_required|tenant_admin_required`; `400 invalid_filter|invalid_cursor`; `422 invalid_time_range`. | Existing `ActivityLog` supports action, user, description, generic resource link and timestamp, but no search endpoint, request ID, tenant scope or structured metadata. Tests: role/tenant isolation, filters, cursor, redaction, immutable event behavior, no secret/content leakage. |

### Implemented tenant membership lifecycle endpoints (unversioned)

| Endpoint | Auth / role / scope | Request | Success response | Statuses and validation | Audit and mandatory tests |
|---|---|---|---|---|---|
| `POST /accounts/api/tenants/{tenant_id}/memberships/{membership_id}/suspend/` | Django session auth + CSRF. Active Tenant Admin or Owner in the path tenant; business tenant only. Path IDs are looked up and authorized server-side. | Empty body. The target must be an active `Member`; this endpoint cannot change Tenant Admin/Owner roles. | `200 {"membership":{"id":"...","userId":123,"role":"member","status":"suspended"}}` | `401`; `403 membership_role_not_allowed`; `404 tenant_admin_required` or target not found in that tenant; `409 membership_state_conflict`. | Emits `SUSPEND_MEMBER` with tenant, actor, membership ID, and target user ID. Test admin/member/owner, cross-tenant IDs, repeat transition, authorization after suspension, no unrelated tenant effects. |
| `POST /accounts/api/tenants/{tenant_id}/memberships/{membership_id}/restore/` | Same requirements as suspend. | Empty body. The target must be a suspended `Member`. | `200 {"membership":{"id":"...","userId":123,"role":"member","status":"active"}}` | `401`; `403`; `404`; `409 membership_state_conflict`. | Emits `RESTORE_MEMBER`. Test restore, repeat transition, audit actor/tenant, and cross-tenant denial. Suspension is membership-scoped: it blocks access to that tenant on subsequent authorized requests, but does not revoke the user's global Django session or other active tenant memberships. |

## 5. Existing-to-proposed endpoint crosswalk

| Capability | Existing evidence in repository | v1 endpoint | Status |
|---|---|---|---|
| Register/login/logout | HTML `POST /accounts/register/`, `/accounts/login/`; JSON `POST /accounts/api/register/`, `/accounts/api/login/`, `/accounts/api/logout/` | `/auth/register`, `/auth/login`, `/auth/logout` | Session-based unversioned JSON endpoints support registration/login/logout; JSON registration intentionally does not auto-login so accepted and duplicate accounts have the same response. Rate limiting and stable v1 routes/envelopes remain missing. |
| Me/profile | `GET/PATCH /accounts/api/me/`; HTML `/accounts/profile/` also changes email/password | `GET /me`, `PATCH /me/profile` | Unversioned API returns backend membership context; profile supports email only. Stable v1 path/envelope remains missing. |
| Settings | No personal settings API/model. | `/me/settings` | Missing; do not add no-op controls. |
| List file/folder | `GET /` and `/drive/folder/{id}/` return HTML; recent/search HTML; detail JSON per item. | `GET /drive/items` | JSON listing and cursor pagination missing. |
| Create folder | `POST /drive/create-folder/` HTML form | `POST /folders` | Existing HTML behavior only; JSON missing. |
| Upload session/direct upload | `POST /drive/upload/` multipart synchronously encrypts and stores locally; `/drive/folder-upload/` uploads folder tree. | `/uploads`, optional content/parts, complete, abort/status | All session endpoints missing. Presigned URL is not present and requires a storage/encryption decision. |
| Download authorization | `GET /drive/files/{id}/download/` streams server-decrypted bytes after owner/share check. | `POST /files/{id}/download-authorizations` | Existing binary route exists; versioned authorization contract missing. |
| Rename/move/copy/trash/restore | Existing file/folder POST form routes and session clipboard/bulk actions; soft-delete and restore exist. | `/files/{id}`, `/folders/{id}`, move/copy/trash/restore | Operations exist as legacy HTML routes with uneven response/idempotency; versioned JSON missing. |
| Quota | No quota model/endpoint found. | `GET /quota/usage` | Missing; cannot report authoritative quota today. |
| Admin user list/suspend/restore/delete | Built-in Django `/admin/`; no custom global user lifecycle endpoint. Tenant membership suspend/restore are available at `/accounts/api/tenants/{tenant_id}/memberships/{membership_id}/{suspend|restore}/`. | `/admin/users...` | Global lifecycle remains missing; tenant endpoint only operates on Member memberships and is tenant-admin scoped. |
| Audit log search | `ActivityLog` model and `log_action`; Django admin registration; no custom query API. | `GET /admin/audit-events` | Missing; existing event coverage incomplete and not tenant/request structured. |

## 6. Open design questions (must be resolved before implementation)

1. **Identity and account classification:** Is public registration always Individual? What creates Business accounts and tenant membership? Until authoritative records exist, return `unclassified` and disable plan/quota decisions.
2. **API auth lifecycle:** Keep same-site Django session auth for all clients, or introduce token/OIDC later? Define production CORS/CSRF origins and login throttling/lockout policy.
3. **Version migration:** Should `/accounts/api/me/` and `/accounts/api/logout/` become aliases to `/api/v1`, or remain supported until a deprecation window expires?
4. **Drive IDs and shared scope:** Keep integer DB IDs or expose opaque public IDs? Should shared items be a separate list endpoint or a `scope` parameter? Define the behavior for a folder inherited share and direct child permission overrides.
5. **Upload transport/encryption:** Keep server-proxied multipart upload, or select direct object storage upload? Direct upload conflicts with current server-side AES-GCM unless an encryption/staging architecture is explicitly selected. Define chunking, resume, checksum source, size limits, MIME allowlist, scanner and retention of incomplete sessions.
6. **Name collisions:** This contract proposes `409` and no silent overwrite. Confirm whether upload should reject, ask client to choose, or auto-rename; keep the rule consistent for restore/copy/move.
7. **Quota accounting:** Define whether trash, pending uploads, shared content, encryption overhead and retained versions count; define reservation consistency and business allocation policy.
8. **Account deletion:** Choose hard deletion, anonymization, or scheduled deactivation; specify treatment of owned files, shares, activity records and legal retention.
9. **Admin scope:** Define site-admin versus Tenant Admin capabilities, self/last-admin protections, step-up authentication, and whether suspend/restore changes Django `is_active` or a separate account state.
10. **Audit policy:** Decide which reads are logged, event retention, request/correlation IDs, structured metadata, tenant scope and redaction. Current `description` is free text and must not be used as a secret-bearing payload.
11. **Settings/support/upgrade:** Select real setting fields and support channel before exposing writable endpoints. A personal upgrade endpoint must re-check Individual status, eligibility and billing authority server-side, and must reject Business members even on direct requests.
12. **Idempotency and async work:** Select key storage/retention, retry semantics, status polling/webhook strategy and job queue before promising replay safety or asynchronous scan states.

## 7. Minimum required test matrix before calling v1 usable

- Authentication: registration validation, login generic failure, session rotation, CSRF, logout invalidation, inactive/suspended accounts, rate limits.
- Authorization: unauthenticated, owner, unrelated user, viewer, editor, trashed item, deleted parent, revoked share, forged user/tenant/parent identifiers; foreign resources return non-enumerating `404`.
- Validation: malformed JSON, unknown fields, path-like/unsafe names, extension changes, max lengths, duplicate case-insensitive names, unsupported MIME/content, size boundaries and batch limits.
- Upload lifecycle: no client-controlled storage identifiers, quota reservation and release, failed/retried/canceled sessions, checksums, encryption, scanning, cleanup, idempotent completion/abort, not available before all required checks.
- File lifecycle: rename/move/copy/trash/restore/permanent deletion, subtree/cycle constraints, conflicts, transactional/partial-failure behavior, storage cleanup and audit records.
- Quota: concurrent uploads, business aggregate/allocation, trash policy, unknown account classification and no cross-tenant leakage.
- Admin/audit: staff versus nonstaff, tenant scoping, last-admin protections, session invalidation on suspend, retention semantics, pagination/filter correctness and secret redaction.
- Contract compatibility: exact status code/error envelope, response schema, cursor binding, idempotency replay/conflict, and no stack trace/provider internals in client-visible failures.

## Implemented direct multipart upload routes

These routes are currently mounted without `/api/v1` and use Django session authentication plus CSRF on unsafe methods:

| Route | Behavior |
|---|---|
| `POST /files/api/uploads/` | Creates a server-owned session and reserves quota. Body: `name`, `size_bytes`, mandatory client-computed SHA-256 `sha256`, optional `folder_id`. The worker recomputes and compares SHA-256 before publish. `Idempotency-Key` is scoped to tenant and initiator. Name conflicts are resolved server-side with ` (2)`, ` (3)`, etc. |
| `POST /files/api/uploads/{upload_id}/parts/{part_number}/authorization/` | Issues a 180-second URL for one server-selected object and part. |
| `POST /files/api/uploads/{upload_id}/complete/` | Persists the ordered client part manifest and a finalization job in one DB transaction. The worker validates the manifest against provider `ListParts`, completes multipart, verifies object metadata/size/SHA-256, and only then publishes. Returns `202`; the file is still unavailable. |
| `GET /files/api/uploads/{upload_id}/` | Returns server-side state and measured bytes; never storage credentials or object references. |
| `POST /files/api/uploads/{upload_id}/abort/` | Aborts and deletes quarantine data when possible and releases the reservation idempotently. |

The finalizer polls the database job table through `python manage.py finalize_uploads`. Quarantine validation computes trusted SHA-256 in the worker; multipart ETags are treated only as provider part tokens. A configured scanner must return exactly `True` for a clean result. Empty files use a server-side zero-byte PutObject because multipart upload requires at least one part. The API currently caps files at 100 MiB; deployment must configure bucket CORS to expose `ETag` to the exact frontend origin. `python manage.py cleanup_uploads` is the scheduled expiry/reconciliation command.

### Publication authorization and recovery (2026-11-08)

Write permission must remain valid until publication commits. The finalizer rechecks the initiating account, tenant membership, Workspace role/status and destination folder before writing PRIMARY and again before committing file metadata. Workspace/tenant/account/membership authorization rows are locked during the short database checks, outside storage I/O. An upload rejected because its destination is no longer writable ends with `state: "failed"` and `failure_code: "destination_not_writable"`; its reservation is released. The client should suggest another destination or restoration of write access, rather than changing the file's contents. A revocation committed after publication does not undo an already published file; subsequent access is governed by the normal resource checks.

Finalization job recovery treats an already `available`/`completed` session as `done` without reading or completing the removed staging object. A reclaimed worker's attempt number fences its metadata, quota and job-state updates. The ten-minute stale timeout remains, with claim timestamps refreshed at database milestones; a slow external operation may still overlap a retry. This does not provide provider-side fencing of an in-flight S3 request or continuous heartbeats during network calls.

### Recent files and Workspace timeline (2026-11-08)

`GET /drive/api/items/?view=recent` returns authorized, live files whose latest `updated_at` or `last_accessed_at` falls within the trailing seven days, including the exact lower boundary. It excludes folders and future activity timestamps, sorts newest first, and retains the existing 100-item response cap. The same window applies when `q` is supplied. This also applies to Workspace Recent through the usual Workspace selector.

The Workspace Activity log chart uses `view=timeline`, a separate manager-only query retaining its 14-day file/folder activity window. This is not an additional user navigation view; `DriveListView` remains unchanged. The audit-event endpoint and its retention are unchanged.

### Platform storage plans and organization boundaries (2026-11-08)

Platform storage management opens the plan catalog. Administrators create personal Drive or personal Workspace presets, then assign an active preset through `PATCH /accounts/api/admin/quotas/{quota_id}/` with exactly `{"plan_code":"...","reason":"8–500 characters"}`. Super Admin permission and CSRF remain required. A null/empty plan code, inactive/unknown plan, wrong scope, or any `limit_bytes` request field is rejected with `400`. The server locks the allocation and selected preset and derives the limit from that preset; usage and reservations remain unchanged. Identical assignment is a no-op without another audit event. Responses still include the effective limit for capacity display.

The platform directory, search totals and allocation history exclude business-organization quota. Attempts to assign a platform plan to a business quota account return `403`. Organization administrators retain their independent, tenant-scoped quota API; platform membership alone does not authorize it. Organization records and audit events are retained in the database.

Existing allocations are not automatically rewritten. A legacy allocation without a plan is shown as not assigned and keeps its effective limit until an administrator selects a plan. Editing a preset preserves previously assigned limits; reassigning a plan applies its current definition. This is storage allocation, not a billing or payment implementation.

### Admin operations review (2026-11-08)

`GET /accounts/api/admin/sessions/?scope=users` includes only non-staff, non-superuser accounts. `scope=admins` includes staff superusers and dedicated PlatformAdminIdentity accounts, matching the administrator directory; unregistered staff are not treated as ordinary users. Dedicated platform administrators serialize as `account_type: "admin"`. Staff/superuser sessions remain protected from the ordinary-user revoke endpoint.

`GET /accounts/api/admin/overview/` also returns `uploads` with `pending_jobs`, `processing_jobs`, `failed_jobs`, `stale_processing_jobs`, `verifying_uploads`, `scanning_uploads` and `oldest_active_job_at` (ISO timestamp or null). Counts are database records, not worker liveness or provider health. Failed jobs are retained totals. Stale processing uses the same ten-minute threshold as worker reclamation, defined by `UploadFinalizationJob.STALE_AFTER`. No object references or storage credentials are returned.

Admin audit search now matches an actor/account, recorded reason, or an exact positive numeric file ID on file actions. It does not search arbitrary metadata. The registered audit implementation remains `admin_logs_api.admin_audit_history_view`, which projects permitted fields; the unused legacy raw-metadata serializer has been removed. Storage-plan/allocation audit remains in its dedicated endpoint and is linked from Admin Audit Logs.

The primary admin menu no longer promotes Security Alerts, Storage Topology or Backups while their services are disconnected. Existing URLs retain honest unavailable states for bookmarks. Dashboard/System Health share one typed overview client, expose upload processing records and support refreshing after failure. This does not implement backup execution, security detection, physical telemetry or file-content access for platform administrators.
# Storage Control Center S1 addendum — 2026-11-08

The implemented S1 endpoints use the existing session-authenticated accounts API convention. These are inventory APIs, not the proposed `/api/v1/storage` provider-control routes. All are gated by `SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED` (default false). With the gate disabled, authorized GETs return 404 before inventory queries. No provider requests are made by these handlers.

Prefixes:

- Platform: `/accounts/api/admin/storage/`, active Platform Admin, Platform-owned clusters only.
- Organization: `/accounts/api/tenants/{tenant_uuid}/storage/`, active business membership with explicit `storage.view` grant. Platform administrators cannot enter this scope by virtue of their Platform role.

Shared GET resources: `capabilities/`, `clusters/`, `clusters/{id}/`, `clusters/{id}/topology/`, `clusters/{id}/nodes/`, `clusters/{id}/nodes/{node_id}/`, `clusters/{id}/disks/`, `clusters/{id}/events/`, `clusters/{id}/operations/`, `clusters/{id}/operations/{job_id}/`.

List envelope: `{count, page, page_size, has_more, results}`. Defaults page=1/page_size=50; bounds page 1..100000, page_size 1..100; malformed values return400. Clusters/nodes support bounded `q`. Ordering uses stable ID tie-breakers. This paging format follows existing admin APIs; it is not the proposed v1 cursor contract.

Topology returns scoped `cluster`, `cluster_id`, `revision`, pools/nodes/disks, health and viewer-specific or shared `layout`. Snapshot bounds are500 nodes,500 pools,2000 disks; exceeding a bound returns422 `topology_snapshot_too_large`, directing callers to paginated lists. It never silently truncates a successful snapshot. Layout is projected to current cluster node IDs and finite coordinates. Reading does not create/update layout or inventory.

Health in S1 is `{status: "unknown", observed_at: null, source: "not_collected", last_success_at: null, stale: true, reason_code: "telemetry_not_configured"}`. Declared capacity is labeled `capacity_source: "inventory"`. A verified connection or registered agent UUID does not certify runtime health. Capabilities report `operations_enabled:false`, `routing_enabled:false`, `stage:"inventory_only"` regardless of future rollout switches.

Organization Owner access administration is the sole S1 metadata mutation, using the Organization prefix only:

- `GET access/{membership_uuid}/` returns `{membership_id, permissions}`; active owner may bootstrap without a prior storage grant.
- `PATCH access/{membership_uuid}/` requires session CSRF and the exact JSON body `{permissions:[...], expected_permissions:[...], reason:"8–500 characters"}`. Supported capabilities: storage.view/configure/operate/approve/monitor. Only an active Organization Owner can delegate; Platform Admin, Org Admin or a storage.configure grant alone cannot delegate. The target must belong to the route tenant. New nonempty grants require an active ordinary target; removal remains allowed for suspended/inactive targets.
- Response200 `{membership_id, permissions, unchanged}`. Identical desired access is an idempotent no-op, including a retry with the old expected set; no duplicate audit. A different stale expected set returns409 `storage_access_conflict` without overwriting newer permissions. Invalid fields/capabilities/duplicates return400; unavailable targets/owners return404. No client tenant/scope selectors accepted in PATCH body.
- `GET access/events/` is Owner-only, paginated access audit; includes before/after capability lists, actor, target resource UUID, reason/time. No mutation/delete audit API exists.

Cross-scope cluster/node/job UUIDs return404 without looking up the other tenant's resource. Denied inventory access is logged with actor/scope/requested UUID only. No credential_ref, endpoint credential, idempotency key, raw SDK error or opaque metadata is serialized. Inventory POST/PATCH/DELETE is unsupported (405 or CSRF403); access PATCH only changes grants/audit and never calls storage.

# Storage Control Center S2 addendum — 2026-11-09

This section supersedes the S1-only capability/mutation description above. Prefixes and session/CSRF/tenant boundaries are unchanged. Capability responses now use `stage:"connect_existing"`, `operations_enabled:false`, actual `routing_enabled` and `lab_probes_enabled` switches. Platform Super Admin has storage.configure; dedicated Platform operators remain read-only. Organization configuration requires explicit view+configure grants.

| Method/resource within either prefix | Contract |
|---|---|
| GET `profiles/` | Approved profiles for this scope; no credentials or credential environment names |
| POST `clusters/connect/` | Exact body `{display_name,slug,profile_id,reason}` and Idempotency-Key; register immutable draft revision; no S3 call |
| GET/POST `clusters/{cluster}/connections/` | Paginated revisions; POST exact `{profile_id,reason}` + Idempotency-Key |
| GET `clusters/{cluster}/connections/{connection}/` | Safe revision metadata and verification state |
| POST `.../{connection}/verify/` | Exact `{reason}`; read-only HEAD/versioning/CORS; read_verified does not authorize binding |
| GET `.../{connection}/probe/` | Latest 20 probe receipts for reload/recovery, no expected digest/authorization |
| POST `.../{connection}/probe/` | Exact `{reason,confirm_lab_fixture:true}`; LAB switch/profile required; new isolated bucket/sample only |
| GET `.../{connection}/probes/{probe}/` | Receipt/checks; `?authorization=1` may issue fresh short-lived GET only while awaiting browser and unexpired |
| POST `.../probes/{probe}/complete/` | Exact `{sha256}`; verify browser digest, clean fixture, then qualify LAB ready |
| POST `.../probes/{probe}/cleanup/` | Empty body; retry/cancel only the server-owned fixture |
| GET/PATCH `binding/` | GET current binding+generation; PATCH `{connection_id,expected_generation,reason,workspace_id?}`; ready connection with completed probe required |

Registration key is scoped to tenant/cluster/action; replay with identical payload returns existing revision, differing payload conflicts409. Reason length8–500. Browser-supplied URL, bucket, network or secret fields are rejected400. Binding identical-target replay is a no-op; a different stale generation returns409. Binding never changes rollout flags. Organization workspace selectors are validated in the same tenant; Platform does not accept a workspace selector.

TLS, credentials, timeout and profile failures are sanitized, with stored codes such as tls_validation_failed/storage_identity_rejected/storage_unreachable/profile_unavailable. HEAD failure returns503 plus safe connection/check state. Probe cleanup failure returns503 and durable cleanup_pending, recoverable through GET receipts/cleanup. Digest mismatch400; expired/busy probe409. Secrets, expected digest and raw SDK errors are never serialized. Presigned authorization is no-store/no-referrer, short-lived, not stored in browser persistence/logs by this UI.

New routed uploads pin their destination once. Existing upload IDs, locations and legacy data do not resolve the latest binding. `GET /files/api/uploads/{id}/` is now read-only: an expired active session reports derived state expired/cleanup_pending without changing DB, quota or storage. The cleanup worker claims expiry and releases quota. Abort handles a session interrupted before its first reservation. The legacy HTML file-upload endpoint returns409 resumable_upload_required while multi-cluster routing is on, avoiding an unpinned bypass; the current multipart browser flow remains supported.

See ADR-0003 and STORAGE_CONTROL_CENTER_S2_RUNBOOK.md for transport assumptions, local rollout, remaining real-LAB gate and rollback restrictions. No arbitrary provisioning/node operation is introduced.

# Storage Control Center S3 addendum — 2026-11-09

Capability adds `topology_enabled`, default false; stage becomes topology only when this flag is on. Control center remains the outer access gate. This does not enable provider/node operations or claim G2 LAB acceptance.

`PATCH clusters/{cluster_uuid}/layout/` accepts exactly `{scope:"personal"|"shared",expected_revision:int,positions:{node_uuid:{x:number,y:number}},viewport:{x:number,y:number,zoom:number}}`. At most500 node coordinates, finite x/y in±1000000, zoom0.1..4, same-cluster node IDs only. Unexpected fields/invalid selectors return400. Layout endpoint returns404 when disabled or cluster/scope unavailable. Personal uses the current principal; browser cannot choose an owner. Shared needs explicit storage.configure or Platform Super Admin policy. Session CSRF remains required.

Success200 returns `{layout,unchanged}`. Same-content replay does not increment revision/audit. Different content with a stale expected revision returns409 layout_revision_conflict and leaves the existing layout intact. Cluster topology revision, node membership, disks, jobs and connections never change through this endpoint. Shared saves append an allowlisted audit event.

Topology snapshot adds `layout_revisions:{personal,shared}` and retains the effective layout (personal then shared fallback). Live/health updates do not use the preference revision. `disks/` and `events/` optionally accept `node_id`; the node must exist inside the selected cluster, otherwise404, malformed UUID400. Event filtering uses the node resource_ref, not arbitrary opaque JSON. Both remain paginated and read-only.

# Storage Control Center S4 addendum — 2026-11-09

Capabilities add `monitoring_enabled` (default false). Both the outer control-center switch and monitoring switch must be on. All endpoints below additionally require storage.monitor, with the existing storage.view/scope boundary. Configure does not imply monitor. Platform identities remain confined to Platform clusters. Disabled/unavailable scope404, inventory-only viewer403, unauthenticated403. Responses are no-store; no scrape occurs in a GET.

| Method/resource within either storage prefix | Contract |
|---|---|
| GET `clusters/{cluster}/telemetry/` | `{cluster_id,configured,revision,event_id,health,expires_at,cluster_metrics,nodes,alerts,sse_available,poll_seconds:30}` |
| GET `clusters/{cluster}/telemetry/stream/` | Session SSE on ASGI + DB/cached-DB sessions; WSGI503 stream_requires_asgi |
| GET `clusters/{cluster}/alerts/` | Paginated incident history including acknowledged/resolved incidents |
| POST `clusters/{cluster}/alerts/{alert}/acknowledge/` | Exact `{expected_revision:int,reason:"8–500 characters"}`; CSRF, fresh active authorization, audit |

Telemetry metrics are allowlisted numbers in bytes/seconds/percent/bytes-per-second as named in the S4 runbook. Missing fields remain missing, never fabricated zero. `nodes` is keyed by scoped inventory UUID and each entry contains `{health,metrics}`. Health is `{status,observed_at,source,last_success_at,stale,reason_code}`. Unconfigured or failed/stale sources report unknown while retaining last known values with provenance. A source identifier is a safe profile ID, not a URL; profiles, PromQL, credentials and raw errors are not exposed. TTL45–900s and capacity thresholds are server-reviewed profile configuration. Inventory endpoints retain inventory-only health; monitoring consumers overlay telemetry explicitly.

SSE sends `event: resync`, `data: {}` and `id: {cluster_uuid}:{revision}:{0|1 stale}`; the client refetches one scoped snapshot. No per-node fetch loop. Last-Event-ID must have the same cluster UUID, bounded numeric revision and stale bit, otherwise400. Initial cursor mismatch triggers resync; matching cursor waits for a change. Heartbeat5s, finite stream~60s, native reconnect/cursor, no URL token, no-transform and X-Accel-Buffering=no. Session, password hash and grants are checked each tick; `event: access_revoked` closes access. Browser keeps30s snapshot reconciliation and client-side expiry even during SSE failure. This behavior is code/fixture verified; reverse-proxy deployment remains G4.

ACK200 returns `{alert,unchanged}`. Acknowledging an already acknowledged incident is idempotent. A different active version or resolved unacknowledged incident409 alert_revision_conflict; malformed body400; foreign alert404. ACK does not resolve an incident or restore health. Fresh verified samples resolve conditions; source failure preserves existing critical incidents. Generation/profile revision fencing and row locks prevent late collector results replacing newer state. Raw metric history remains upstream TSDB. See ADR-0005 and the S4 runbook.

## P2 Organization provisioning — 2026-11-17

Phạm vi development theo [ADR-0012](ADR-0012-organization-managed-identities-and-private-my-drive.md). Các route dưới đây giữ session/CSRF và namespace hiện có. Schema chỉ được kiểm chứng trên PostgreSQL test riêng; không chứng nhận đã rollout serving. Tenant business là Organization, không có Organization model thứ hai.

| Route | Actor, input và kết quả |
| --- | --- |
| GET/POST `/accounts/api/admin/organizations/` | Platform Admin. GET giữ directory/pagination, thêm `capabilities` và `pendingAdministratorInvitation`. POST chỉ nhận `{name,slug,admin:{username,email},limit_bytes,member_limit_bytes,reason}` cùng UUID `Idempotency-Key`; tạo Tenant, initial OWNER invited và My Drive riêng. |
| GET/POST `/accounts/api/tenants/{tenant}/members/` | Active Org OWNER/ADMIN. GET giữ `members`, thêm `managed`, `myDriveWorkspaceId` và capabilities. POST chỉ nhận `{username,email,limit_bytes,reason}` cùng UUID `Idempotency-Key`; chỉ tạo MEMBER mới trong đúng Organization. |
| POST `/accounts/api/admin/organizations/{tenant}/reinvite/` | Platform Admin; `{reason}`; chỉ initial managed administrator còn pending. |
| POST `/accounts/api/tenants/{tenant}/memberships/{membership}/reinvite/` | Org OWNER/ADMIN; `{reason}`; chỉ managed MEMBER pending trong đúng Tenant. |
| POST `/accounts/api/organization-invite/accept/` | Public, bắt buộc CSRF; `{uid,token,password1,password2}`; token còn hiệu lực, account pending và password hợp lệ thì trả `{activated:true}`. Không tự đăng nhập. |
| POST `/accounts/api/tenants/{tenant}/memberships/{membership}/{suspend|restore}/` | Org OWNER/ADMIN; giữ API MEMBER hiện có, không nhận reason. Managed account suspend chặn login, restore chỉ cho account đã activation; bảo toàn identity, content, quota và audit. |

Creation trả `201`, replay cùng actor/payload trả `200`, conflict trả `409`; response `{member,myDrive:{tenantId,workspaceId,ownership:"organization"},storageReady}` và thêm `organization` khi tạo Organization. API không trả password hoặc activation link. Replay vẫn kiểm quyền hiện hành; không tạo thêm account, quota hoặc email. Không attach, promote hoặc đổi password tài khoản đã tồn tại. Limits là số nguyên hữu hạn không âm, member limit không vượt Tenant limit; `reason` dài 8–500 ký tự. Field errors dùng `fieldErrors` với keys phẳng, gồm `admin.username`/`admin.email`.

Invitation reuse `ADMIN_INVITES_ENABLED` và email gate hiện có; chưa cấu hình thì creation trả `503`, không tạo identity dang dở. Không dùng console/file/dummy mail backend để tránh ghi token. Người nhận inactive, non-staff, password unusable cho tới activation; reinvite chỉ pending và làm link cũ mất hiệu lực. Frontend `/organization-invite` nhận `uid`/`token` trong URL fragment và xóa fragment ngay, không dùng query hoặc browser persistence. Locmem chỉ phục vụ fixture test; không gửi email thật trong nghiệm thu development.

`GET /accounts/api/me/` trả thêm `myDrive` home pointer, độc lập current selected Workspace. Không có selector, managed employee dùng own My Drive trong Organization; selector explicit phải được authorize trước lookup mặc định. Missing/revoked home membership hoặc thiếu private drive bị deny, không fallback Personal/General. Personal account hiện hữu giữ behavior cũ. Owned My Drive không nằm trong collaborative Workspace directory hoặc API invite/archive/membership thông thường. Org/Platform Admin không có quyền nội dung ngầm; explicit share vẫn theo policy hiện có. Business My Drive tính Tenant + Member quota, không nhận Workspace starter quota.

`storageReady` là kiểm tra metadata binding/revision phù hợp tại thời điểm response, không phải provider health hoặc nghiệm thu storage thật. P2 không tạo/bind cluster, đổi routing, key hoặc credentials. Thiếu Enterprise binding tiếp tục fail closed cho upload. Không convert tài khoản hoặc di chuyển dữ liệu cũ; migration/rollout serving cần phê duyệt riêng.
