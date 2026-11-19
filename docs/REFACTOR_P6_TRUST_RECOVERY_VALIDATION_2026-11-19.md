# P6.1.5 — Kiểm chứng directory, mở khóa thiết bị và recovery custody

## 1. Phạm vi và baseline

Baseline `6d2ee3c4d712de058c8638d6a5c2e1f486cb87cb`, nhánh `feature/p6-crypto-feasibility`, [Draft PR #8](https://github.com/binos2303/BlueDrive/pull/8). 77 ca P6.1 bao gồm NIST AES-GCM, RFC 9180, PyCA HPKE hai chiều và browser fixture. Nhánh P6.1.5 là `feature/p6-trust-recovery-hardening`. Mọi khóa và dữ liệu thử nghiệm được sinh riêng. Không có thay đổi với serving, cấu hình rollout, schema ứng dụng, upload/download production hoặc `cse_v1`. Path EXCLUDE và recovery material hiện hữu không nằm trong candidate. P4/P5 vẫn có 32 + 5 volumes khi kiểm kê chỉ đọc.

## 2. Findings và ranh giới tin cậy

| Finding P6.1 | Evidence | Disposition P6.1.5 |
| --- | --- | --- |
| Checkpoint nằm trong RAM và mất khi tạo client mới | SOURCE VERIFIED trong `DirectoryTrust` và REPRODUCED trong P6.1 | FIXED/TESTED trong prototype mới. IndexedDB transaction lưu sequence/digest, kiểm tra lại trong giao dịch, giữ anchor khi abort hoặc nhận proof không hợp lệ. |
| Client mới có thể nhận lại signed entry đã revoke | REPRODUCED trong P6.1 với anchor đúng và client chưa thấy revoke | FIXED/TESTED với witness độc lập trung thực. Client có profile mới hoặc bản sao cũ nhận head hiện thời theo nonce mới. |
| Relay có thể gửi lại record hoặc checkpoint đã được ký | SOURCE VERIFIED. Chữ ký cũ vẫn đúng | TESTED nonce, head digest và sequence qua signed witness response, scoped directory state và linkage. |
| UI khóa vẫn dùng được CryptoKey lấy từ IndexedDB | REPRODUCED trên browser fixture cũ, gồm reload/restart | TESTED trong prototype bundle mã hóa. Phiên LOCKED chỉ còn ciphertext và public metadata trong kho. Script cùng origin sau unlock vẫn có thể gọi API được cấp quyền hoặc quan sát vật liệu khi nhập. |
| Profile có thể mang quyền sử dụng khóa | REPRODUCED với bản sao Chrome cùng máy | TESTED trên cùng browser, profile bundle mã hóa cần vật liệu bên ngoài, giữ checkpoint cũ và hỏi witness mới. Cross-device copy và bảo đảm phần cứng NOT VERIFIED. |
| Khóa Enterprise do một service software giữ | SOURCE VERIFIED trong P6.1 và prototype emulator | TESTED process boundary và independent policy. Emulator giữ toàn bộ khóa, native HSM/KMS và cryptographic quorum NOT VERIFIED. |
| P6.1 replay ledger ở RAM, fail sau khi đánh dấu handled | SOURCE VERIFIED trong `recoveryService` cũ | FIXED/TESTED với receipt + audit transaction, process crash, concurrent requests và restore snapshot nhất quán. Snapshot cũ của authority/ledger cần qua restore fence riêng trước production. |
| Policy P6 chưa được duyệt | SOURCE VERIFIED trong design §18 | NEEDS APPROVAL. |

Phạm vi threat gồm relay có thể chặn, thay hoặc replay dữ liệu, profile có thể mất/restore, custodian đơn lẻ hoặc Platform Admin thiếu quyền, worker có thể dừng ở bất kỳ điểm nào. Giả định pin ban đầu đến từ kênh độc lập đã xác thực, authority/witness giữ đúng trạng thái và khóa, thiết bị chưa bị compromise, thời gian kiểm tra nằm trong ngưỡng đã công bố. Một witness độc lập xác nhận head giống như hỏi cơ quan cấp thẻ xem thẻ còn hiệu lực ngay tại thời điểm sử dụng. Thiết bị tự đọc thẻ cũ có thể kiểm chữ ký in trên thẻ nhưng vẫn cần hỏi người cấp thẻ để biết thẻ đã bị thu hồi.

## 3. Directory, canonical format và bootstrap

- `checkpoints.mjs` sử dụng ECDSA P-256 với JSON array có thứ tự cố định và domain versioned riêng cho entry, state, checkpoint, witness và authority rotation. Scope là Tenant hoặc Organization dưới Tenant business theo ADR-0012. Entry ghi subject/device/purpose, key ID và epoch, active/revoked, raw public key. Directory digest SHA-256 bao phủ các entry canonical, sắp xếp theo subject/device/purpose. Checkpoint ký tenant/sequence/prior digest/state digest/fingerprint authority/thời điểm publish. Fixture giới hạn 256 entries và 256 links khi bắt kịp từ một checkpoint đã lưu.
- Pin verifier lấy fingerprint SHA-256 của SPKI qua kênh bootstrap riêng. Rotation cần chữ ký cả khóa hiện tại và khóa mới trên tenant, hai fingerprint, sequence cutover và digest checkpoint trước đó. Client giữ phạm vi sequence của từng pin để kiểm lịch sử và chỉ chấp nhận witness proof từ pin hiện hành. Cần operator quyết định kênh pin provisioning, update, emergency revoke và khôi phục trust khi pin cũ compromise.
- Client tạo nonce 32 byte cho từng lần hỏi. Authority ký nonce + tenant + checkpoint digest + issued/expires từ head hiện có và kiểm tra head lần nữa trước trả. Client kiểm signature, nonce, linkage, local monotonicity và time window 30 giây, clock skew 2 giây, witness deadline 5 giây. Đây là tham số fixture. Freshness là bằng chứng về head tại lúc authority trả lời trong giới hạn thời gian. Rollout phải chọn TTL, giám sát clock và quy tắc cho thao tác in-flight băng qua revocation.
- Authority journal SQLite `synchronous=FULL` kiểm tra append theo sequence và giữ checkpoint công khai ngoài profile. Test mở lại journal và xác nhận vẫn từ chối entry revoke với client mới. Trong browser, witness chạy ở process runner và được gọi qua binding test, không dùng Django/Next hoặc private key trong trang. Production cần service TLS/identity, custody khóa, audit, availability và restore fencing. Restore journal cũ cùng profile cũ có thể mất lịch sử đã quan sát nếu authority cũng tụt trạng thái.
- Browser store lưu sequence/digest trong giao dịch strict IndexedDB. Client phát hiện rollback hoặc equivocation so với head đã thấy. Cấp quyền thất bại khi dữ liệu local sai và sẽ cần bootstrap lại được kiểm soát sau khi đồng bộ với authority. Enrollment ký proof, endorsement và nonce cùng scope, đánh dấu consume trong cùng transaction với CAS checkpoint. Đây là ledger theo profile. Một enrollment coordinator dùng chung có replay ledger bền vững và đối chiếu challenge gốc là điều kiện production để ràng buộc nhiều profile/thiết bị hoặc restore.

### Witness A và transparency B

**A được chọn cho fixture.** Signed head theo challenge và nhật ký tiến tới kiểm được freshness với pinned authority độc lập. Availability phụ thuộc authority. Issuer bị compromise/cố tình split-view có thể trả head khác nhau cho các client chưa từng chia sẻ checkpoint. **B** thêm Merkle inclusion/consistency, monitor và witness độc lập để audit lịch sử và so head giữa client. B cần vận hành log, retention, monitor và cách xử lý fork, phù hợp khi cần phát hiện split-view toàn cục ngoài giả định hiện tại. Prototype A không thực hiện giao thức Certificate Transparency. [RFC 9162](https://www.rfc-editor.org/rfc/rfc9162.html), [RFC 8954 về nonce kháng replay](https://www.rfc-editor.org/rfc/rfc8954.html).

## 4. Freshness theo hành động

| Hành động | Khuyến nghị | Trạng thái |
| --- | --- | --- |
| Enrollment và phê duyệt thiết bị | Pin độc lập, proof of possession và endorse từ signer active mới xác minh. Nonce một lần. | FEASIBILITY VERIFIED trong profile fixture. Coordinator chung NEEDS APPROVAL. |
| Cấp envelope mới và internal sharing | Xác minh pin, head mới, exact recipient and key epoch trước ký grant/wrap. Cần kiểm tra lại khi trả kết quả hoặc commit. | Directory primitive TESTED. Ghép vào API và policy NEEDS APPROVAL. |
| Personal / Enterprise recovery | Fresh identity/generation và người nhận đã đăng ký. Enterprise cần request + approval có scope, epoch và expiry độc lập. | Test theo §6–7. Liên kết witness, enrollment và recovery policy tại production NEEDS APPROVAL. |
| Revocation | Authority publish tombstone. Chặn cấp mới ngay khi thấy head mới, xử lý URL còn TTL và khóa đã cấp theo policy. | TESTED local checkpoint, rotated pin, client mới và device unlock. |
| Đọc đã được cấp quyền khi offline | Cân nhắc cho phiên còn khóa, exact signed/pinned version và cache đã xác minh. Offline không chứng minh được revoke mới. | PROPOSED. Prototype yêu cầu witness khi mở phiên mới. Một phiên đang mở có timeout, và đối tượng mới vẫn cần freshness. |

## 5. Device unlock và browser matrix

Bundle dùng AES-256-GCM với domain riêng, key ID và generation gắn vào AAD. Unlock material là 32 byte CSPRNG độc lập do user/fixture giữ ngoài profile. Đường vào kiểm danh tính và freshness trước khi hỏi vật liệu và lần nữa sau giải mã. Session giữ key handles non-extractable trong closure, chỉ mở crypto operations. Timeout idle mặc định 60 giây trong fixture, logout/relock bỏ reference và chặn kết quả đã chạy dở, không tái mở object session đã logout. Giới hạn JS GC khiến việc xóa hoàn toàn bộ nhớ không thể chứng minh. Không lưu plaintext DEK hoặc dùng password tài khoản làm key. Ca PRF unavailable hoặc user cancel fail closed.

| Phương án | Trade-off và trạng thái |
| --- | --- |
| Persist CryptoKey non-extractable | Hiệu năng và offline thuận tiện. Cùng origin vẫn dùng được handle, profile Chrome cùng máy đã sao chép được quyền sử dụng. UI lock không đủ. |
| Bundle mã hóa + secret entropy cao ngoài profile | FEASIBILITY VERIFIED cho khóa ở trạng thái LOCKED, wrong/missing secret, copy, password reset không cấp key, revoke, concurrency, idle và logout. Cần thao tác unlock và kênh giữ vật liệu riêng trên thiết bị khác. JavaScript độc hại vẫn có thể chờ lúc mở khóa. Thiết bị bị compromise nằm ngoài bảo đảm. |
| WebAuthn PRF với user verification | PROPOSED nếu authenticator/RP/client được phê duyệt. PublicKeyCredential client capability chỉ là tín hiệu. Cần thử registration/assertion PRF, UV, mất authenticator, sync/portability, off-device recovery và authorization để bắt đầu rollout. [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/). |
| Isolated crypto origin | PROPOSED khi có thể cô lập input/key storage và thu hẹp message capability. Vẫn phải kiểm origin, user intent, XSS của origin mới, portability, offline và độ phức tạp tích hợp. NOT RUN. |

| Browser fixture | IndexedDB, unlock, two-tab, revoke, recovery | Spool | PRF |
| --- | --- | --- | --- |
| Chrome Windows 157.0.8103.80 | PASS reload/restart, abort/corruption, profile copy checkpoint 1 → 2 và khóa khi thiếu vật liệu | OPFS resume PASS | Client advertised |
| Firefox Windows 159.0 | PASS reload/restart, abort/corruption. Profile copy NOT RUN | OPFS resume PASS | Client advertised |
| Playwright WebKit Windows 27.2 | PASS reload/restart, abort/corruption. Profile copy NOT RUN | UNSUPPORTED `UnknownError`, fresh intent + fresh DEK PASS | Unknown |
| Chromium Pixel 7 emulation | PASS browser fixture. Device proof và profile copy NOT RUN | OPFS resume PASS | Client advertised |
| Android/iOS vật lý, authenticator thực | NOT RUN, thiết bị/authenticator chưa được cung cấp | Chưa đo | PRF/UV phần cứng NOT RUN |

Chỉ resume khi đã xác minh spool và receipt. Khi thiếu một trong hai, fixture khởi tạo encryption intent và DEK mới. Không có fallback lưu plaintext. Phương án đi production còn cần ma trận Safari thật và mobile performance/usability. [IndexedDB specification](https://www.w3.org/TR/IndexedDB-3/), [Web Cryptography Level 2](https://www.w3.org/TR/webcrypto/).

## 6. Enterprise custody và ranh giới quorum

- **POLICY QUORUM VERIFIED.** Policy fixture đăng ký ba custodian với ba public key khác nhau, request ký bởi requester đã cấp scope, duyệt bằng ít nhất hai chữ ký khác nhau, từ chối tự duyệt/custodian revoke/relay giả quyền. Ticket ký ràng buộc Organization, Workspace, file/version, envelope digest, recipient fingerprint/key ID, case, nonce, expiry và recovery epoch. Approval sử dụng cùng TTL của ticket fixture.
- **INDEPENDENT RECOVERY SERVICE VERIFIED** trong child-process fixture. Relay gửi request, approvals, envelope và public key. Authority process riêng đọc policy và private custody DB, thực hiện HPKE unwrap → rewrap. Relay nhận sealed envelope và không có operation export key/plaintext. Cùng OS user quản lý các tiến trình test. Fixture chưa kiểm OS principal/container boundary. Role flags do relay gắn không cấp quyền. Private key nằm trong SQLite emulator, nên host/operator compromise vượt khỏi khả năng bảo vệ của fixture.
- **CRYPTOGRAPHIC QUORUM NOT VERIFIED.** Chưa có HSM, KMS hoặc threshold implementation được kiểm trên đúng operation và suite. CloudHSM công bố quorum cho một số key operations và công bố ECDH/X9.63 trong SDK; cả hai tài liệu chưa chứng minh M-of-N bắt buộc cho P-256 DHKEM/HKDF của RFC 9180 và DEK rewrap đúng ranh giới. KMS ECDH có thể giữ ECC private key nhưng API trả shared secret. Kiểm soát IAM + independent rewrap service là hướng chọn nếu operator chấp nhận service trust và kiểm được path release/key usage. Threshold custody cần primitive/suite tương thích được review độc lập. Không tự tạo threshold HPKE hay Shamir.
- Ưu tiên thẩm định service độc lập + HSM/KMS như một lựa chọn vận hành, đồng thời giữ Enterprise recovery ngoài rollout nếu yêu cầu cryptographic quorum chưa đạt. Thử nghiệm tiếp theo phải chứng minh cơ chế ngăn single custodian/service principal thực hiện derived secret và unwrap ngoài đúng ticket. [CloudHSM quorum operations](https://docs.aws.amazon.com/cloudhsm/latest/userguide/key-quorum-auth-chsm-cli-service-names.html), [CloudHSM PKCS #11 mechanisms](https://docs.aws.amazon.com/cloudhsm/latest/userguide/pkcs11-mechanisms.html), [KMS DeriveSharedSecret](https://docs.aws.amazon.com/kms/latest/APIReference/API_DeriveSharedSecret.html), [NIST threshold project](https://csrc.nist.gov/Projects/threshold-cryptography).

### Crash, audit và restore

SQLite giữ khóa case ID, nonce và target exact version duy nhất. Giao dịch giữ write lock suốt unwrap/rewrap trong fixture. Case receipt chỉ chứa recipient ciphertext; audit/outbox ghi cùng commit. Failing audit rollback cả hai. Bốn thử nghiệm chấm dứt worker trước unwrap, sau unwrap, sau rewrap và sau commit trước IPC reply. Trước commit retry cùng ticket còn hiệu lực làm lại; sau commit trả đúng ciphertext đã ghi. Hai process dùng chung SQLite tạo một biên nhận và một audit. Ticket khác cho cùng version bị từ chối theo policy fixture, cần cơ chế supersede được duyệt nếu nghiệp vụ có nhiều recovery chính đáng. Snapshot sau commit bằng SQLite backup được mở ở đích khác, rewrap đã ghi vẫn xác minh và ledger từ chối case xung đột. Host power failure, backup bị rollback, audit gửi ra ngoài và notification delivery NOT RUN. Production cần authority restore fence, external audit và outbox retry, key retention/rotation, reconciliation và xử lý expiry khi sự cố kéo quá TTL.

## 7. Personal recovery kit

Giữ định dạng random offline kit P6.1 và domain cũ, chọn rõ trường xuất cho bundle. Test bảo toàn AES-GCM export integrity, 32 byte độc lập, wrong/lost kit, password reset, cross-Tenant, stale generation bị từ chối khi trusted generation đã tiến, snapshot restore, last device revoked và thiết bị mới dùng unlock material riêng. Cần duy trì trusted generation ngoài bundle để chống rollback khi restore. Mất mọi bản sao vật liệu và thiết bị được cấp quyền khiến file không thể giải mã. Platform Admin chỉ có thể xử lý login theo quyền hiện hành. Passphrase-derived kit và benchmark KDF ngoài phạm vi, do đề xuất vẫn dùng nguồn random offline. Mobile còn cần đo thao tác nhập/import và kênh lưu vật liệu.

## 8. Policy baseline, prerequisites và rollback

| Policy | Khuyến nghị và phạm vi | Decision |
| --- | --- | --- |
| Internal sharing | Signed grant tới approved device exact key epoch. Enterprise thêm Organization membership và policy. | NEEDS APPROVAL |
| Public links | CSE public links disabled trong v1. | PROPOSED |
| Cross-Tenant sharing | Disabled mặc định. | PROPOSED |
| Device revocation | Chặn cấp grant/URL mới, ghi TTL còn hiệu lực và residual access của key đã cấp. | NEEDS APPROVAL |
| Key rotation | Versioned key IDs, retain reader chính xác, re-encrypt khi policy yêu cầu. Enterprise giữ custody theo key epochs. | NEEDS APPROVAL |
| Malware scan | Tenant yêu cầu trusted scanning mà capability chưa sẵn sàng phải fail closed. | BLOCKED cho Tenant cần capability chưa có |
| Preview | Client-side, format allowlist và sandbox. | PROPOSED |
| ZIP | Client-side sau verify và có size cap. | PROPOSED |
| Metadata search | Giữ phạm vi metadata được duyệt, phân loại metadata nhạy cảm theo Tenant. | NEEDS APPROVAL |
| Quota | Logical plaintext và physical ciphertext accounting, Enterprise theo Organization quota. | NEEDS APPROVAL |
| Downgrade | CSE-required fail closed cho mọi đường cấp dữ liệu. | NEEDS APPROVAL |
| Rollback | Stop writer, preserve reader, key custody, pinned versions và khả năng restore. | NEEDS APPROVAL |
| Legacy | Giữ AES reader và exact pinned object version/revision. | NEEDS APPROVAL |

Rollback fixture là dừng chạy prototype và giữ baseline P6.1 cùng production binaries hiện tại. Không rollback dữ liệu hoặc recovery material. Production prerequisites gồm phê duyệt authority/bootstrap/freshness, unlock/custody, thư viện HPKE và `cse_v1`, browser support, Personal recovery distribution, Enterprise recovery chính thức hoặc loại khỏi rollout, cùng rollback/restore rehearsal và review bảo mật độc lập.

## 9. Quality gates và Git

- `npm --prefix frontend/experimental/cse test` PASS 103, 0 FAIL, 0 SKIP, với Python 3.12/PyCA pinned. Giữ toàn bộ 77 test P6.1. Browser dùng `npm --prefix frontend/experimental/cse run test:browser -- chromium firefox webkit mobile` trên Windows và Chromium trên workflow. Provider, thiết bị vật lý và serving ngoài phạm vi fixture.
- Node fixture SQLite là API có sẵn trong Node 24. Không thêm runtime/package dependency. npm audit không có advisory ở thời điểm kiểm tra, ba registry signatures và ba attestations xác minh. [Node 24 SQLite API](https://nodejs.org/docs/latest-v24.x/api/sqlite.html).
- Local frontend unit PASS 163, lint/typegen/TypeScript PASS, production build 41/41 routes, prototype-output scan 983 files PASS. Repository safety chạy trên working tree và index, kèm secret pattern scan chỉ báo path nếu có, và whitespace. Backend workflow vẫn dùng PostgreSQL test service cô lập. Provider tests SKIP được báo riêng.
- Commit subject và reviewer evidence trên Draft PR của nhánh này, target `feature/p6-crypto-feasibility`. Gate CI chỉ tính `repository-safety`, `backend` và `frontend` PASS trên SHA của candidate. Dùng [commit list của candidate](https://github.com/binos2303/BlueDrive/compare/feature/p6-crypto-feasibility...feature/p6-trust-recovery-hardening) và [Actions của nhánh](https://github.com/binos2303/BlueDrive/actions?query=branch%3Afeature%2Fp6-trust-recovery-hardening) để đối chiếu SHA và run, tránh tự tham chiếu SHA trong chính commit chứa tài liệu.

Kết luận phạm vi kỹ thuật là fixture feasibility. Security approval và **P6.2 IMPLEMENTATION READY** vẫn chờ các quyết định và bằng chứng ở trên.
