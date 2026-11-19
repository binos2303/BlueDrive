# P6.1 — Cryptographic feasibility và security validation

[Báo cáo P6.1.5](REFACTOR_P6_TRUST_RECOVERY_VALIDATION_2026-11-19.md) ghi riêng kết quả witness, checkpoint bền vững, unlock và custody emulator trên baseline của tài liệu này.

Ngày 19/11/2026, Asia/Bangkok. Baseline P5 development `d344ec90ba4b4ea6cfe1dd9654b560e81064d740` và [P6 design](REFACTOR_P6_SECURITY_DESIGN_2026-11-19.md) `7d73359f9e1a67a48a49bc2b9aaa84e5eee3bb21` của Draft PR #7. Nhánh `feature/p6-crypto-feasibility` kế thừa đúng design head. Exact candidate và CI nằm trong Draft PR/checks.

**Crypto feasibility đạt trong phạm vi fixture công bố khi các gate exact-head được xác nhận. P6.2 implementation readiness PARTIAL.** WebKit Windows chưa có OPFS resume. Thiết bị vật lý, cryptographic quorum và security design approval vẫn là gate riêng.

## Ranh giới và dependency map

Node và Playwright chạy file tổng hợp, test key mới mỗi lượt và các vector công khai trên loopback. Authority directory/recovery fixture tách vai trò với relay mô phỏng Django. PyCA nhận dữ liệu fixture qua stdin. Log chỉ ghi trạng thái, tên ca và số liệu tổng hợp. Cùng-origin script, browser/OS/authority bị chiếm và rollback cả checkpoint nằm ngoài bảo đảm của fixture.

| Contract | Điểm chạm hiện tại | Ý nghĩa cho integration |
| --- | --- | --- |
| Upload và resume | [Upload client](../frontend/components/drive/upload-service.ts) gửi plaintext slices khoảng 8 MiB | Crypto record 1 MiB và ciphertext part 8 MiB có biên riêng. Resume chỉ dùng sealed bytes cùng signed receipt đã xác minh. |
| Publication, scan và pinning | [Finalizer](../backend/files/finalization.py), [P5](REFACTOR_P5_FILE_LIFECYCLE_2026-11-18.md) | Tách ciphertext integrity khỏi scan/plaintext validation. Giữ P5 transactional publish và pinned revision/VersionId khi triển khai. |
| Quota | [Reservation](../backend/files/quota.py) | Đo wire size hiện tại. Chính sách logical quota và physical accounting chờ duyệt. |
| Identity, share và download | [ADR-0012](ADR-0012-organization-managed-identities-and-private-my-drive.md), [access](../backend/accounts/access.py), [sharing](../backend/sharing/services.py), [download](../backend/files/views.py) | Session vẫn cần ACL. Device trust, signed grant và exact file version bổ sung riêng khi mở key. |
| Compatibility, storage | [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md), [AES legacy](../backend/security/aes_service.py), [P4](PLATFORM_QUALIFICATION_2026-11-13.md) | Giữ reader legacy, binding và qualification P4/P5 theo đúng phạm vi cũ. Prototype không gọi DB/S3 phục vụ. |

## Libraries và dependency security

- `@hpke/core` 1.10.1 và `@hpke/common` 1.13.0, MIT, là ứng viên. Core phát hành 08/11/2026, upstream duy trì releases/security policy, công bố Node >=16. Fixture kiểm Node 24.18.0 và ba browser engines Windows. Dùng Base mode, DHKEM(P-256, HKDF-SHA256), HKDF-SHA256, AES-256-GCM, IDs 0x0010 / 0x0001 / 0x0002. Upstream ghi giới hạn formal audit. Cần review độc lập trước khi phê duyệt runtime. [Release](https://github.com/dajiaji/hpke-js/releases/tag/%40hpke%2Fcore%401.10.1) · [Upstream](https://github.com/dajiaji/hpke-js) · [Advisories](https://github.com/dajiaji/hpke-js/security/advisories).
- `@noble/hashes` 2.4.0, MIT, cùng version frontend baseline, dùng SHA-256 incremental. AES-GCM, ECDH, HKDF, ECDSA dùng WebCrypto/library. PyCA cryptography 48.0.0, cùng version backend, là Rust/OpenSSL-backed HPKE reference độc lập. API PyCA 48 single-shot hỗ trợ `info`; phép interop hai chiều dùng AAD rỗng. RFC vector kiểm AAD khác rỗng riêng. Native alternatives như CIRCL có thể làm reference khác. Bridge/WASM client sẽ tăng tooling và supply-chain scope. [PyCA HPKE](https://cryptography.io/en/48.0.0/hazmat/primitives/hpke/) · [CIRCL](https://github.com/cloudflare/circl).
- Lockfile riêng pin integrity của ba npm packages. `npm audit` ghi 0 findings và `npm audit signatures` xác minh ba chữ ký registry, ba attestations. CI dùng `--ignore-scripts`. Không có kết luận an toàn chỉ từ advisory scan. Production manifests/lockfile không đổi.

## Crypto và format

| Gate | Kết quả |
| --- | --- |
| NIST AES-256-GCM | PASS hai vector CAVP IV 96/tag 128, gồm plaintext rỗng và 16 bytes có AAD. ZIP NIST trả 403 tại host này. Dùng vector NIST vendored tại PyCA 48.0.0 với SHA-256 nguồn trong `vectors.json`. Không phải chứng nhận CAVP. [NIST CAVP](https://csrc.nist.gov/projects/cryptographic-algorithm-validation-program/cavp-testing-block-cipher-modes) · [Vector](https://raw.githubusercontent.com/pyca/cryptography/48.0.0/vectors/cryptography_vectors/ciphers/AES/GCM/gcmEncryptExtIV256.rsp) |
| RFC 9180 và HPKE interop | PASS exact suite, enc và ba records có AAD theo sequence. Chỉ trích public IKM/outputs, bỏ trường private key gốc. PyCA seal → WebCrypto open và WebCrypto seal → PyCA open PASS với dữ liệu và key ngẫu nhiên fixture. Sai private key, info, AAD, enc, tag, ciphertext, suite, recipient, Tenant/Version đều từ chối. [RFC 9180](https://www.rfc-editor.org/rfc/rfc9180.html) · [Vector commit RFC](https://github.com/cfrg/draft-irtf-cfrg-hpke/blob/5f503c564da00b0687b3de75f1dfbdfc4079ad31/test-vectors.json) |
| Format `cse_v1` PROTOTYPE | PASS offset/header 104 bytes, prefix 152 bytes, AAD và tag 128 bits, ECDSA raw 64 bytes. So deterministic digest tạo độc lập bằng PyCA AESGCM. Round-trip 0, 1 byte, các biên chunk và 100 MiB. Không thay bytes theo P6 Design. |
| Parser, tamper và export | PASS bounds trước allocation, flags, u64 overflow, scope, wrong key/nonce/AAD, missing/reorder/duplicate, truncate/append, tag và producer signature sai. Ca AEAD ký lại dữ liệu đã sửa bằng key fixture để riêng kiểm tag. Export sink không nhận plaintext khi verify fail. |
| Nonce và resume | PASS 100 counter data và manifest reserved phân biệt trong một DEK. Mỗi seal mới sinh DEK/prefix bằng CSPRNG. Counter uniqueness trong key theo cấu trúc, entropy collision giữa các lần sinh là xác suất. Resume kiểm digest, scope và chữ ký. Receipt mất, spool bị sửa hoặc intent mơ hồ buộc tạo version/DEK mới. |

Giống kiện hàng có dấu niêm phong, retry gửi lại đúng kiện đã niêm phong. Nếu phiếu xác thực không còn khớp, thử lại bằng kiện mới với chìa khóa mới.

## Directory, device và recovery

- **Directory PASS.** Trusted device endorsement yêu cầu kiểm proof cả signing key và HPKE recipient key. OOB fingerprint pin authority. Các ca relay thay recipient key, ngầm thêm device, đổi Tenant/subject/purpose/authority, grants giả hoặc hết hạn, producer signature sai, revoked device, epoch rollback và equivocation đều bị từ chối. Client mới có anchor, thiếu freshness vẫn nhận record lịch sử hợp lệ. Khuyến nghị endorsement/OOB cùng checkpoint độc lập. TOFU thiếu bảo đảm first-contact và freshness. Checkpoint fixture trong RAM, witness và rollback qua restart chưa kiểm.
- **Device lifecycle PASS theo matrix.** Hai non-extractable CryptoKey đi qua IndexedDB structured clone, reload, browser process restart; export private key bị chặn. Context tạm không thấy keys của persistent profile. Cùng origin vẫn dùng được key handle đã lưu khi UI khóa. Profile copy Chrome cùng máy Windows giữ được khả năng mở key. Cần duyệt boundary khóa thực sự và mô hình tin cậy frontend origin.
- **Personal recovery PASS.** Bundle AEAD bind version, scope, generation, public recovery key. Entropy offline 32 bytes độc lập login. Thiết bị mới rewrap bằng kit và xác thực account, có recovery signature cho enrollment. Sai kit, thiếu kit/device, account/Tenant sai, epoch cũ và password reset đơn thuần đều bị chặn. Fixture không dùng app PostgreSQL. Rotate policy không thu hồi secret/ciphertext đã giữ từ trước.
- **Enterprise policy PASS · CRYPTOGRAPHIC QUORUM NOT VERIFIED.** Hai chữ ký độc lập cùng ticket, distinct requester/recipient, checked Tenant, scope, TTL, epoch, replay, recipient fingerprint và envelope digest trước HPKE rewrap và audit. Denial one custodian, revoked, self-approval, admins thiếu custody và sai envelope đều PASS. Service fixture giữ nguyên recovery key. HSM/KMS hoặc recovery service cần chứng minh quyền dùng key được enforce ở ranh giới riêng và hỗ trợ suite/rewrap. Threshold custody cần giải pháp đã review và kiểm độc lập các shares. Threshold signature không chứng minh threshold decrypt. [CloudHSM quorum](https://docs.aws.amazon.com/cloudhsm/latest/userguide/quorum-authentication.html) · [FROST](https://www.rfc-editor.org/rfc/rfc9591.html).
- **KDF benchmark NOT RUN.** Kit dùng entropy ngẫu nhiên. Argon2id/scrypt memory-hard cần lựa chọn module browser/WASM đã review và đo trên mobile. PBKDF2 có trong WebCrypto, chủ yếu đặt chi phí CPU. Cần giới hạn params trước allocation để tránh DoS và bind version/salt/params nếu bổ sung passphrase. Chưa chọn profile production. [Argon2id](https://www.rfc-editor.org/rfc/rfc9106.html) · [scrypt](https://www.rfc-editor.org/rfc/rfc7914.html) · [PBKDF2](https://www.rfc-editor.org/rfc/rfc8018.html).

## Browser và performance

Windows 10.0.26300, Playwright 1.65.0, headless loopback. Mỗi browser kiểm AES-GCM, P-256 ECDH/ECDSA, HPKE, format và device lifecycle. Browser tạm, dữ liệu synthetic và keys chỉ cho fixture. Profile được dọn sau lượt.

| Môi trường | Crypto, IDB, reload/restart | OPFS và sealed receipt | 1 MiB seal/export (ms) | JS heap peak mẫu |
| --- | --- | --- | ---: | --- |
| Chrome 157.0.8103.80 Windows | PASS, profile-copy cùng máy mở được key | PASS qua reload/restart | 273 / 253 | 15,5 MiB |
| Firefox 159.0 Windows | PASS, profile-copy NOT RUN | PASS qua reload/restart | 156 / 117 | NOT AVAILABLE |
| WebKit 27.2 Windows | PASS crypto trong memory, profile-copy NOT RUN | UNSUPPORTED, probe `UnknownError`, resume NOT RUN | 102 / 99 | NOT AVAILABLE |
| Chrome 157 Pixel 7 emulation | PASS, profile-copy NOT RUN | PASS qua reload/restart | 105 / 89 | 14,5 MiB |
| Android và Safari/iOS vật lý | NOT RUN, thiếu thiết bị | NOT RUN | NOT RUN | NOT RUN |

| Plaintext Chrome desktop | Wire bytes | Seal ms (MiB/s) | Verified export ms (MiB/s) | OPFS write / read+verify (ms) | JS heap mẫu (MiB) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0 bytes | 152 | 37 (N/A) | 21 (N/A) | 11 / 43 | 3,3 |
| 1 MiB | 1.048.744 | 273 (3,66) | 253 (3,96) | 35 / 269 | 15,5 |
| 10 MiB | 10.486.072 | 3.260 (3,07) | 2.017 (4,96) | 212 / 2.254 | 68,1 |
| 50 MiB | 52.429.752 | 8.623 (5,80) | 6.526 (7,66) | 645 / 4.326 | 79,1 |
| 100 MiB | 104.859.352 | 10.673 (9,37) | 10.339 (9,67) | 918 / 4.324 | 80,1 |

Seal gồm hash, encrypt, ký và ghi. Export gồm hash và hai lượt decrypt. Read gồm digest, chữ ký và đối chiếu retry. 2 crypto buffers mỗi record, tổng cực đại quan sát 2.097.168 bytes. Không gồm Blob nguồn, spool, part 8 MiB dùng cho retry, runtime backing storage hoặc RSS. Heap là mẫu JS, không đo toàn browser. Hai workers thật chạy AES-GCM 1 MiB đồng thời, output round-trip đúng và ciphertext khác nhau. Chrome estimate lúc 100 MiB báo khoảng 10,1 GiB quota, usage khoảng 100 MiB. Lỗi quota được inject tại sink để kiểm interrupted seal. Không lấp đầy disk hay benchmark network không thuộc fixture. Số đo một lượt song song với checks khác, không là SLA.

## Findings và hướng kiến trúc

| Mức | Finding | Điều kiện xử lý |
| --- | --- | --- |
| Cao với threat XSS/profile | Non-extractable key persisted vẫn usable ở cùng origin khi UI khóa, cùng máy có thể copy profile. | Duyệt trust boundary của unlock và delivery frontend, đánh giá isolated origin/device-backed unlock và thực nghiệm thiết bị thật. |
| Cao với directory freshness | Pin authority ngăn substitution nhưng client thiếu checkpoint có thể nhận dữ liệu cũ hợp lệ. | Chốt authority ngoài relay, OOB/endorsement và signed monotonic checkpoint/witness. |
| Trung bình | @hpke/core private-only thất bại vì library cần tái tạo public key. | Prototype truyền cả pair khớp directory, private vẫn non-extractable. Mở security/library review trước runtime. |
| Trung bình | Digest-only receipt không đủ và WebKit Windows gặp lỗi OPFS thực tế. | Prototype yêu cầu chữ ký, gate capability resume và dùng intent mới khi receipt không tin cậy. |
| Gate mở | Two approvals dùng một recovery key tại service. | Operator chọn HSM/KMS hoặc threshold custody, thử enforce quorum và recovery restore trước triển khai. |

Giữ `cse_v1` từ P6 Design và hướng per-device WebCrypto pair. Rollback development gỡ prototype/CI và docs nối tiếp. Khi integration, giữ dual-reader và exact version/revision cùng hoàn cảnh recovery. Ưu tiên forward-fix hoặc dừng encrypted writes theo policy, giữ đường đọc đã xác minh.

## Product security decisions

| Mục | RECOMMENDED | VERIFIED | NEEDS APPROVAL |
| --- | --- | --- | --- |
| Public sharing | Tắt trong CSE v1 | NOT RUN | Trust và capability |
| Internal sharing | Signed grant theo device/version | Fixture PASS | Grant UX và quy tắc chia sẻ |
| Cross-Tenant sharing | Mặc định tắt | Denial replay PASS | Ngoại lệ |
| Device revoke | Chặn issuance mới, kiểm epoch | Fixture PASS, key đã tải còn dùng được | Freshness và retention |
| Key rotation | Lưu public keys lịch sử, DEK mới cho version mới | Epoch/rotation fixture PASS | Scope triển khai |
| Offboarding | Revoke membership và device, giữ data đúng Tenant | Contract ADR-0012, integration NOT RUN | Recovery owner và retention |
| Malware scan | Fail closed nếu yêu cầu trusted scan khi chưa có mechanism đã duyệt | NOT RUN | Endpoint attestation hoặc delegated scan. `client_scan_passed=true` không là bằng chứng |
| Preview và ZIP | Giải mã client trong boundary đã duyệt, xuất file đã xác thực, size bound | NOT RUN cho preview/ZIP | Nội dung active và giới hạn |
| Metadata | Giảm trường clear, giữ dữ liệu cần cho quyền/quota | Header scope/size bound PASS | Metadata visibility |
| Logical quota | Plaintext length có kiểm wire format | Wire formula PASS | Personal/Workspace/Enterprise rules |
| Physical accounting | Đếm wire/staging/versions và giữ reservation lifecycle | Overhead đo fixture | Physical cap và reconciliation |
| Downgrade protection | Required CSE fail closed | Unsupported format flags bị từ chối | Rollout policy |
| Legacy compatibility | Giữ plaintext và AES legacy readers | Baseline CI | Các mốc migration |
| Data recovery | Offline Personal, Enterprise custody riêng | Personal và policy PASS; threshold NOT VERIFIED | Kit UX và key custodians |
| Rollback | Dừng writer, giữ reader/key/revision và restore rehearsal | NOT RUN | Chính sách vận hành và owner |

## Chạy lại và nghiệm thu

Từ `frontend/` với Node 24 và Python/PyCA reference đã pin

```text
npm ci --ignore-scripts
npm --prefix experimental/cse ci --ignore-scripts
python -m pip install --only-binary=:all: -r experimental/cse/requirements-reference.txt
npm --prefix experimental/cse test
npx playwright install chromium firefox webkit
npm --prefix experimental/cse run test:browser -- chromium firefox webkit mobile
npm run lint
npx next typegen
npx tsc --noEmit
npm run build
node experimental/cse/check-build.mjs
```

Windows dùng Chrome đã cài cho Chromium/mô phỏng mobile. `P61_PYTHON` có thể chỉ interpreter Python reference riêng. CI dùng pinned Playwright Chromium, chạy crypto suite và browser fixture. Local **77 PASS, 0 FAIL/SKIP** gồm 32 ca trust/recovery, frontend lint/typecheck **PASS**, unit **163 PASS**, build **41/41**, **983** emitted server/static files và traces qua check không chứa prototype. Repo safety, scoped secret scan, dependency audit, diff và CI exact-head ghi trên Draft PR. Backend production source/schema và contracts giữ nguyên. Dùng baseline backend workflow PostgreSQL test, không chạy provider trên serving.

Trước P6.2 cần phê duyệt trust bootstrap và freshness, suite/library, format, browser/device matrix và custody/recovery; tiếp đó chốt scanner, sharing, revocation, quota và rollback có đường đọc đã xác minh. Kết quả feasibility chỉ áp dụng phạm vi fixture, security design approval thuộc reviewer/operator.
