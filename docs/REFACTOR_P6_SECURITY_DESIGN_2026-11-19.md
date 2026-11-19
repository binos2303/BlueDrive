# P6 — Thiết kế mã hóa phía client và khôi phục khóa

Ngày 19/11/2026, Asia/Bangkok. **PROPOSED · SECURITY DESIGN.** Thiết kế triển khai tiếp theo của [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md).

## 1. Tóm tắt đề xuất

Browser mã hóa từng version bằng DEK ngẫu nhiên trước khi gửi ciphertext tới SeaweedFS. Django giữ vai trò control plane cho Tenant, Workspace, quota, routing, publication và audit. Thiết bị được cấp quyền nhận DEK qua key envelope. Enterprise có đường recovery riêng từng Organization, dùng phê duyệt kép và khóa ngoài Django. Personal dùng thiết bị đã duyệt hoặc bộ kit offline của chính người dùng. Tách việc mở khóa dữ liệu khỏi đăng nhập và reset mật khẩu.

Source hiện tại vẫn gửi `file.slice()` qua multipart, finalizer tải staging để kiểm SHA-256, MIME và scanner nếu có, rồi ghi `is_encrypted=False`. Reader legacy dùng `SECUREDRIVE_AES_KEY` để mở các DEK cũ. P6 giữ đường đọc legacy và bổ sung một format riêng. Bằng chứng P4/P5 xác nhận lifecycle hiện hành trong phạm vi fixture. [P0 F08](REFACTOR_P0_BASELINE_2026-11-16.md) · [P4](PLATFORM_QUALIFICATION_2026-11-13.md) · [P5](REFACTOR_P5_FILE_LIFECYCLE_2026-11-18.md) · [Upload client](../frontend/components/drive/upload-service.ts) · [Finalizer](../backend/files/finalization.py) · [AES legacy](../backend/security/aes_service.py).

## 2. Mục tiêu bảo mật

- Plaintext, DEK và private keys chỉ xuất hiện trong browser/client tin cậy hoặc trong thiết bị/hệ thống recovery được cấp quyền. SeaweedFS và Filer giữ ciphertext. Django xử lý ciphertext và metadata cần cho nghiệp vụ.
- Bảo vệ confidentiality trước việc lộ ứng dụng DB, kho object hoặc backup riêng lẻ. Client xác thực manifest, nguồn phát hành và từng chunk. Chỉ công nhận publication sau khi server xác minh bytes ciphertext và chốt quyền/quota trên revision đã pin.
- Quyền file và quyền nhận envelope đều theo Tenant, Workspace, subject và thiết bị. Metadata tối thiểu như tên, cấu trúc folder, kích thước, thời điểm, thành viên và access pattern vẫn có thể lộ ở control plane. Tên file và tên folder trong P6 vẫn là metadata của ứng dụng.
- Phạm vi recovery quyết định ai có thể giải mã. Enterprise có thể khôi phục dữ liệu qua custodians được duyệt. Tuyên bố zero-knowledge hoặc chống compromise origin cần một mô hình trust và bằng chứng riêng.

## 3. Threat model

Các test ở cột cuối là tiêu chí dự kiến. Từ chối tại API phải xảy ra trước khi trả URL hoặc envelope. Đối chiếu client bao gồm việc quan sát đầu ra giải mã, dữ liệu cache và audit.

| Actor hoặc sự kiện | Asset và đường rủi ro | Ranh giới và kiểm soát | Rủi ro còn lại | Acceptance test |
| --- | --- | --- | --- | --- |
| External attacker | Session, URL và envelopes qua endpoint web hoặc link bị lộ | TLS, session/CSRF, RBAC từng request, S3 private và URL ngắn hạn exact key/version | URL còn hạn cho phép lấy ciphertext. Metadata qua lỗi trả về cần review | Anonymous, CSRF thiếu/sai, link hết hạn và cross-Tenant đều bị từ chối theo đúng lớp |
| Compromised user session | Session hợp lệ xin URL, enroll device hoặc mở recovery | Hạn chế envelope theo device, fresh authentication và xác nhận từ thiết bị đã duyệt hoặc recovery authority | Session bị chiếm có thể xem metadata được phép và tải ciphertext | Session fixture thiếu device approval không enroll, lấy envelope hoặc recover được |
| XSS | Script cùng origin gọi crypto bằng key đã mở hoặc đọc plaintext | CSP chặt, Trusted Types nơi hỗ trợ, giảm script phụ thuộc, worker, sandbox khác origin cho nội dung active, short unlock | Script đủ quyền trên origin vẫn có thể dùng key. Worker và non-extractable key giới hạn bề mặt nhưng không tạo ranh giới cùng origin | Kiểm CSP/preview isolation, dữ liệu cache/log và hành động cần xác nhận. Kiểm giới hạn của key đã unlock trong review |
| Stolen browser storage | IDB/OPFS hoặc profile bị sao chép | Ciphertext spool, key thiết bị non-extractable, không giữ DEK/secret dạng rõ. Đánh giá bảo vệ local bằng authenticator/OS keystore | Browser profile backup/migration có thể mang key hoặc quyền dùng key, tùy nền tảng | Sao chép fixture profile đã khóa, kiểm khả năng dùng key trên máy khác và loại dấu vết plaintext |
| Compromised device | OS hoặc phiên đã mở lấy nội dung/DEK | Device revoke, scope nhỏ, giảm thời gian giữ key, rotate đối với dữ liệu sau thời điểm phát hiện | Dữ liệu thiết bị đã dùng có thể bị giữ lại | Revoke máy thử nghiệm rồi cấp file/version mới, xác minh máy chỉ còn dữ liệu đã lưu từ trước |
| Malicious employee | Lấy key của người khác, export file được chia sẻ, lạm dụng rewrap hoặc gửi ciphertext không giải mã được | ACL, scope riêng Employee My Drive, ký grant, không cấp khóa từ role chung, audit và kiểm AEAD tại client | Recipient hợp lệ có thể sao chép hoặc rewrap ngoài hệ thống. Producer hợp lệ có thể gửi ciphertext không mở được | Employee A bị chặn yêu cầu key B, A chỉ thấy version theo grant. Client reject AEAD fail ngay cả khi backend kiểm đúng ciphertext |
| Organization Admin | Lạm dụng quản trị account, storage hoặc recovery | Tách role admin, custodians, approvers và recipient; chính sách dual control theo Organization | Người đủ quorum có thể khôi phục trong phạm vi đã duyệt | Org Admin mặc định không nhận envelope Employee My Drive; một approver không đủ quorum |
| Platform Admin | Đổi policy hoặc public keys để nhận Enterprise content | Không có Enterprise recovery key cấp Platform. Trust anchor policy và key directory pin độc lập với Platform admin | Nếu kiểm soát cả frontend phát hành hoặc trust bootstrap, có thể nhắm các client mới hoặc đang mở | Platform admin bị chặn đọc theo đường thường và không tự cấp recovery/đổi trust anchor đã pin |
| Compromised Django | Capability trái phép, thay public keys, phát JavaScript độc hại nếu cùng chuỗi deploy | Chữ ký directory/grant từ authority độc lập, policy kí duyệt ở client, origin phát hành client được quản trị tách biệt nếu threat yêu cầu | Origin hoặc build client bị chiếm có thể làm lộ plaintext trong phiên. Server có thể chặn phục vụ hoặc phát ciphertext cũ | Thay key/binding trên control plane fixture, client reject với anchor độc lập. Review riêng giả thiết client origin |
| Compromised application PostgreSQL | Đọc envelopes/ACL, sửa key ID, phiên bản và quota | Private key ngoài DB, chữ ký version/grant và epoch được client đối chiếu với trust state độc lập | Lộ metadata, mất availability, rollback cùng trust state client mới còn rủi ro | Restore DB lệch epoch, sửa recipient/version/scope, client tin cậy từ chối |
| Compromised SeaweedFS | Đọc ciphertext, thay/truncate/reorder version, xóa bytes | AES-GCM chunk/manifest, detached producer signature, ciphertext digest, pin VersionId trên đúng revision | Lộ kích thước/access pattern và từ chối phục vụ; replay version hợp lệ theo hàng dưới | Tamper, mất byte, version sai và cross-bucket denial trên fixture thật |
| Compromised backup | Sao chép DB/S3 dump, ciphertext và envelopes cũ | Backup custody tách riêng, recovery key/kit ngoài bundle, hạn chế ACL, consistency receipts, giữ epoch chống rollback ngoài DB backup | Lộ metadata. Nếu lộ đồng thời backup và recovery material liên quan thì có thể giải mã | Restore bundle fixture thiếu key chỉ thấy ciphertext. Thử recovery được duyệt trên bundle đúng và từ chối sai Tenant |
| Malicious key-directory replacement | Thay recipient public key trước upload/share hoặc thêm device | SPKI fingerprint, chứng minh sở hữu key, endorsement ký bởi authority đã pin, thiết bị mới kiểm fingerprint qua kênh độc lập, monotonic epoch/revocation | First-contact chỉ tin API có thể bị thay khóa. Client origin độc hại có thể bỏ kiểm | Directory trả key mới hợp lệ về cú pháp nhưng thiếu endorsement hoặc epoch cũ, client dừng trước wrap |
| Replay/rollback | Thay ciphertext lẫn metadata bằng phiên bản/envelope cũ có chữ ký hợp lệ | AAD cố định version ID, client kiểm grant epoch, current head có trạng thái tin cậy độc lập hoặc pin đã quan sát | Client mới hoặc rollback cả anchor/checkpoint vẫn có thể nhận lịch sử hợp lệ. Chỉ tình huống có trusted state mới có bảo đảm chống rollback | Replay envelope khác version/grant, thử old head trên client đã pin và biểu diễn đúng giới hạn client mới |
| Lost device/private key | Mất khả năng mở DEK, mất thiết bị cuối | Recovery kit Personal hoặc quorum Enterprise, enroll key mới và rewrap phạm vi đã duyệt | Mất cả authority recovery thì dữ liệu CSE có thể không phục hồi | Diễn tập mất thiết bị cuối với kit đúng, kit sai, thiếu kit và enroll device mới |
| Employee offboarding | Thiết bị cũ tiếp tục tìm URL/envelope, hoặc dữ liệu công ty mất key | Revoke Organization membership/context và devices/grants theo policy, đảm bảo Enterprise recovery envelope, rotate cho version tương lai | Plaintext, DEK và URL trước revoke có thể còn trên thiết bị. Chính sách giữ hồ sơ cần business review | Thu hồi giữa staging/publication và giữa share/download, thử recovery có approval, giữ đúng scope Personal riêng |

## 4. Trust boundaries

| Vùng | Được giữ hoặc xác minh | Ranh giới quyền |
| --- | --- | --- |
| Browser/client tin cậy | Plaintext, key thiết bị, DEK tạm, kiểm signature/AEAD và trust epoch | Secure context, nguồn phát hành được duyệt, không gửi account password vào crypto worker. Non-extractable `CryptoKey` giới hạn export qua API nhưng không bảo vệ trước OS hoặc app origin đã chiếm quyền. [Web Cryptography Level 2](https://www.w3.org/TR/webcrypto-2/) |
| Django và PostgreSQL ứng dụng | ACL, policy, directory public, envelopes, sizes, digest ciphertext, object route, metadata | Session/CSRF và scope theo [access](../backend/accounts/access.py), [sharing](../backend/sharing/services.py) và [ADR-0012](ADR-0012-organization-managed-identities-and-private-my-drive.md). Quyền Organization, Workspace và Platform độc lập. |
| S3/Filer | Ciphertext, immutable key/version, multipart receipts và metadata vận hành | Đọc/ghi đúng Storage Binding đã pin và identity bucket scope. CSE bổ sung confidentiality, không thay TLS, SSE nếu có, version pinning, storage isolation hoặc S3 IAM. |
| Key directory trust và recovery | Chứng thực public key/epoch, recovery private keys và phê duyệt | Key authority, credential và audit có phân quyền riêng ngoài application DB. Policy signer và recovery decryptor dùng các key khác nhau. Control plane chỉ lưu public attestations và wrapped material. |

Trong kho hồ sơ, bộ phận cấp phiếu nhận có thể biết ai được nhận kiện hàng. Chỉ thiết bị giữ chìa khóa hợp lệ hoặc nhóm recovery có đủ phê duyệt mới mở được kiện. Việc tách này giảm tác động khi sổ cấp phiếu bị lộ.

## 5. Key hierarchy và lựa chọn unlock

| Phương án | Bảo mật khi lộ server/backup và tấn công offline | UX, multi-device và recovery | Quản trị, rotation và bảo trì |
| --- | --- | --- | --- |
| Passphrase mã hóa độc lập | Tách secret khỏi đăng nhập. Blob bị lộ vẫn cho thử offline theo KDF và entropy passphrase | Gõ thêm secret, dễ quên. Có thể mở bản key bundle trên nhiều máy. Reset login không mở được dữ liệu | Rewrap bundle khi đổi passphrase. Phải quản lý tham số KDF, hỗ trợ thiết bị yếu và tránh mất toàn bộ quyền khi quên |
| Unlock suy từ mật khẩu đăng nhập | Mật khẩu Django/SSO không thành khóa đáng tin. Lộ credential hoặc frontend và blob tăng tác động. KDF chỉ tăng phí thử offline | Ít thao tác, reset phức tạp, passkey/SSO không có shared password để derive | Authentication migration, reset và rotation bị dính crypto. Đề xuất bỏ phương án này |
| Key riêng từng thiết bị, recovery envelopes riêng | Khóa ngẫu nhiên, non-extractable nơi hỗ trợ, giảm phụ thuộc mật khẩu. Thiết bị mở khóa và trust authority vẫn là bề mặt quan trọng | Enroll bằng thiết bị đã duyệt hoặc kit/quorum. Reset login giữ quy trình unlock riêng. Chi phí rewrap lịch sử theo batch | Revoke và rotate theo key ID/epoch. Recovery policy riêng theo Tenant. Cần hỗ trợ client/browser và vận hành custody |

Khuyến nghị phương án thiết bị. Mỗi FileVersion sinh DEK AES-256 ngẫu nhiên bằng CSPRNG của nền tảng. Mỗi thiết bị có cặp key recipient và cặp key ký riêng, đặt `extractable=false` khi API/library cho phép. Không tái dùng key thiết bị, recovery key, AES legacy hoặc credential storage cho vai trò khác. Key directory giữ public key/suite/id/epoch. Private key tạo từ entropy nền tảng, độc lập với username, email và user ID. DEK chỉ giữ trong thời gian xử lý, xoá tham chiếu sau khi dùng. JavaScript garbage collection giới hạn bảo đảm zeroization.

Nếu hỗ trợ lớp unlock từ passphrase cho kit/device export, ưu tiên Argon2id đã duy trì và được audit phù hợp runtime. Argon2id và scrypt cần module browser/WASM, memory budget và test mobile. PBKDF2-HMAC-SHA-256 có trong WebCrypto và dễ liên thông hơn, nhưng chỉ đặt chi phí CPU nên cần đánh giá kỹ trước khi hỗ trợ fallback có version. Đề xuất benchmark profile RFC, đo p95 CPU/RAM trên thiết bị tối thiểu, đặt ngưỡng chấp nhận và giới hạn cứng tham số khi đọc bundle để tránh DoS. Lưu salt ngẫu nhiên, thuật toán và version/params trong bundle và xác thực chúng bằng envelope. Chọn profile sau review và benchmark, tránh tự hạ chi phí khi thiết bị yếu. [Argon2id RFC 9106](https://www.rfc-editor.org/rfc/rfc9106.html) · [scrypt RFC 7914](https://www.rfc-editor.org/rfc/rfc7914.html) · [PBKDF2 RFC 8018](https://www.rfc-editor.org/rfc/rfc8018.html).

## 6. Vòng đời thiết bị và directory

1. Thiết bị tạo key ký và key nhận theo suite cố định. Sau step-up, chứng minh sở hữu cả hai key bằng chữ ký và xác nhận challenge chỉ key nhận mới mở được. Bind challenge với account, Tenant, device public keys, hết hạn và nonce dùng một lần. Endorsement từ thiết bị đã tin, authority recovery hoặc bootstrap ban đầu đã xác minh fingerprint tạo bản ghi active.
2. Thiết bị mới xác minh trust anchor/fingerprint qua cơ chế độc lập phù hợp chính sách và nhận bản ghi directory có chữ ký, Tenant/subject, key purpose và epoch. Thiết bị đã tin xác minh monotonic epoch trước khi wrap. Với recipient lần đầu, xác minh fingerprint hoặc attestation theo chính sách. Không tự dùng key thay thế chỉ vì API trả một public key mới.
3. Thiết bị cũ hoặc recovery client unwrap DEK từng version rồi rewrap cho thiết bị mới trong phạm vi được duyệt. Batch có phân trang, idempotent theo (version, key ID, grant epoch), theo dõi tiến độ và audit. Khoảng chờ trước khi có envelope là trạng thái cần cấp key.
4. Khi rotate, khóa mới có ID/epoch mới. Lưu public keys lịch sử để kiểm chữ ký version cũ và xử lý nghi vấn compromise theo mốc thời gian. Revoke ngăn issuance và nhận envelope mới, audit và cảnh báo thành công/thất bại. Chốt retention trước khi hủy key thế hệ cũ sau khi kiểm đủ coverage. Đổi mật khẩu không tự unlock, rewrap hoặc xóa thiết bị.

Step-up bằng WebAuthn là phương án đánh giá. PRF/hardware storage chỉ là khả năng tùy thiết bị và browser, cần feature detection và kiểm portability. Authenticator synced và profile browser clone có đặc tính riêng. [WebAuthn Level 3](https://www.w3.org/TR/webauthn-3/#prf-extension).

## 7. Personal recovery

Đề xuất kit offline do client tạo gồm recovery recipient key ngẫu nhiên và authority ký phục hồi với mục đích tách biệt. Giữ private material trong bản export được bọc bằng secret ngẫu nhiên entropy cao do người dùng giữ ngoài tài khoản. Bundle dùng AEAD, version và AAD cho account/scope/key IDs. Chốt encoding, custodian và UX xác minh kit trước bật ghi CSE. Public recovery keys và endorsement được đăng ký theo epoch, mỗi version có recovery envelope. Django không giữ secret offline hoặc bản private dạng rõ.

Recovery yêu cầu account authentication và chứng minh quyền kiểm soát kit, rồi thêm key thiết bị, unwrap/rewrap đúng các version. Notify các thiết bị còn lại và ghi audit. Mất kit nhưng còn thiết bị cho phép thay kit và rewrap có kiểm đếm. Mất mọi thiết bị và kit dẫn đến trạng thái không thể giải mã. Reset login vẫn hoạt động, quyền giải mã có gate riêng.

## 8. Enterprise recovery

- Org Admin quản lý account, Storage Admin quản lý cluster/binding, recovery approver duyệt từng yêu cầu, custodian thực thi, và recipient đã đăng ký nhận key được rewrap trong phạm vi đó. Người yêu cầu và recipient của cùng một case không được tính vào quorum phê duyệt. Org Admin không mặc định nhận quyền giải mã Employee My Drive.
- Đề xuất quorum hai người độc lập trong ba custodians cho mỗi Organization. Khóa recovery chuyên dụng do Organization giữ trong HSM/KMS hoặc môi trường độc lập đạt yêu cầu. Không dùng một recovery root toàn Platform. Chứng minh HSM/isolated recovery runtime hỗ trợ suite và thao tác rewrap hoặc giới hạn private material trước khi chọn sản phẩm.
- Ticket phạm vi hẹp gồm reason, Organization, version IDs, recipient key ID, case ID, thời hạn và policy epoch. Kiểm step-up, chữ ký approvals, quorum, retention/offboarding và chống replay, rồi rewrap DEK theo đúng ticket. Đường thường trả về envelope mới cho recipient được duyệt. Audit gửi tới nơi kiểm soát độc lập, log ID/timestamp/outcome và notify theo policy. Khóa recovery và plaintext không đi qua Django.
- Enterprise required-recovery chặn publish nếu thiếu envelope đúng Org/key epoch. Khi mất quorum hay recovery key, quy trình continuity đã diễn tập quyết định khả năng phục hồi. Rotate theo khóa Org và generation, rewrap history theo policy, chỉ retire sau khi kiểm coverage và backup restore. Quorum có thể giải mã trong phạm vi phê duyệt và vẫn là một bên được tin cậy.

## 9. Ciphertext format đề xuất

Format `cse_v1` dùng AES-256-GCM với tag 128 bit. Mọi integer dưới đây là unsigned big-endian. UUID dùng 16 byte chuẩn network order. Từ chối magic, version, header length, flags và ciphertext length ngoài profile trước đọc/allocate theo input. Dùng phép tính có bounds, kiểm u64 trước khi chuyển sang JavaScript Number. Giữ encoding canonical để các browser và backend cùng kiểm được. [NIST SP 800-38D](https://csrc.nist.gov/pubs/sp/800/38/d/final).

| Offset byte | Field | Encoding |
| --- | --- | --- |
| 0–7 | Magic | ASCII `BLUDCSE1` |
| 8–15 | Format, header length, flags | u16 = 1, u16 = 104, u32 = 0 |
| 16–79 | Tenant, origin Workspace, crypto file ID, crypto version ID | Bốn UUID theo thứ tự này, IDs do control plane đặt trước encryption |
| 80–95 | Plaintext size P, chunk size C, chunk count N | u64, u32, u32. Profile v1 dùng C = 1 MiB, N = ceil(P/C), N = 0 khi P = 0 |
| 96–103 | Nonce prefix | 8 byte ngẫu nhiên cho DEK/version |
| 104–151 | Manifest record | AES-GCM mã hóa 32 bytes `plaintext_sha256`, tag 16 bytes, với nonce dành riêng cho manifest |
| Từ 152 | Data records | Record i gồm ciphertext dài bằng plaintext chunk i, sau đó 16 bytes tag. Không padding hoặc compression. Record cuối theo P. |

Tổng kích thước wire `152 + P + 16*N`. File rỗng có 152 byte và vẫn xác thực được SHA-256 của plaintext rỗng. Manifest là header có AAD xác thực cùng encrypted digest record. Django lưu detached producer signature, producer key ID và SHA-256 qua toàn bộ container. Canonical signature payload đề xuất là ASCII `BlueDrive/CSE/sign/v1` + một byte 0 + UUID key ID + 152 bytes prefix + 32 bytes ciphertext SHA-256. Dùng ECDSA P-256/SHA-256 theo profile, signature raw 64 byte `r || s` (WebCrypto), test chuyển đổi rõ nếu backend library dùng DER. Chuẩn bị fixture vectors và review định dạng này trước code.

## 10. Nonce, AAD và anti-rollback

- Nonce 96 bit gồm prefix trên và bộ đếm u32. Data indices `0..N-1`; manifest index `0xffffffff` dành riêng và không có data ở index đó. Mỗi version/attempt mã hóa mới có DEK riêng, kể cả lúc retry sau khi thiếu bằng chứng về lần mã hóa trước. Không mã hóa record lần hai dưới cùng cặp DEK/nonce.
- AAD chính xác là ASCII `BlueDrive/CSE/aead/v1` + byte 0 + header 104 byte + u8 loại record (0 data, 1 manifest) + u32 index + u32 độ dài plaintext record. Header khóa chặt format, Tenant, origin Workspace, file/version ID, tổng độ dài, chunk size và count. Không đưa tên, path hoặc display metadata thay đổi trong rename/move vào AAD. V1 cho rename/move cùng Workspace. Chuyển scope cần đích mới và encrypt/version mới theo policy, hoặc báo unsupported.
- Client đối chiếu header với version/scope được xin, exact object size và chữ ký producer. Verify manifest tag trước data, verify tag từng record và từ chối thiếu/thừa, trùng, reorder, substitute hoặc sai record length. Xác minh SHA-256 ciphertext và plaintext trước chốt full-file download/ZIP. File lớn có thể dùng hai lượt qua spool ciphertext đã seal để giữ bộ nhớ hữu hạn và chỉ export vào đích người dùng chọn sau kiểm toàn file. File nhỏ có thể giữ kết quả trong bộ nhớ giới hạn. Không lưu plaintext vào vùng cache do app quản lý. Preview range, nếu sau này hỗ trợ, chỉ xuất record đã auth theo manifest và object version.
- Tag và producer signature phân biệt version thật với tamper. Khi có state version/epoch đã pin hoặc signed head do authority độc lập cấp, client reject rollback thấp hơn checkpoint hợp lệ. Pin `VersionId` ràng buộc phiên bản storage mà API cấp nhưng tự nó không xác thực current head. Version cũ do user chủ động chọn phải hiển thị đúng version và vẫn qua ACL.

## 11. Key envelopes và compatibility cryptography

Đề xuất dùng HPKE RFC 9180 Base mode với DHKEM(P-256, HKDF-SHA256), HKDF-SHA256 và AES-256-GCM cho wrap DEK 32 byte. Dùng implementation đã review. P-256 và các primitive có sẵn trong WebCrypto, còn toàn bộ HPKE là một protocol riêng. `@hpke/core` là ứng viên dùng WebCrypto, upstream báo chạy trên nhiều browser và có vectors RFC. Upstream cũng ghi chưa formal audit. Chọn library/version sau review maintenance, supply chain, chấp nhận non-extractable key, browser/mobile, interoperability và trạng thái audit. X25519 là ứng viên khác nếu policy và browser matrix đạt. Chrome 133 và Firefox 130 công bố hỗ trợ X25519, WebKit có thay đổi enable mặc định. [RFC 9180](https://www.rfc-editor.org/rfc/rfc9180.html) · [hpke-js upstream](https://github.com/dajiaji/hpke-js) · [Chrome](https://developer.chrome.com/release-notes/133?hl=en#x25519-algorithm-of-the-web-cryptography-api) · [Firefox](https://bugzilla.mozilla.org/show_bug.cgi?id=1904836) · [WebKit](https://bugs.webkit.org/show_bug.cgi?id=284368).

Probe primitive tại secure-context fixture bằng Chrome 157.0.8103.80 kiểm P-256 ECDH, HKDF, AES-GCM 256/128-bit tag, P-256 ECDSA raw-64, non-extractable key qua structured clone và sự hiện diện OPFS API. Fixture thiếu Firefox/WebKit runtime. Đây là bằng chứng API trong một browser. Interop HPKE, persistence sau relaunch, OPFS quota, Safari/iOS, Android và hardware/enterprise recovery là gates trước khi chọn profile cuối.

Envelope framing có version/suite, Tenant/origin Workspace/file/version IDs, recipient kind (device, Personal recovery hoặc Organization recovery), recipient key ID, grant/policy epoch, HPKE `enc` và ciphertext. Bind `info` với domain `BlueDrive/CSE/dek/v1`, dùng fixed fields/canonical encoding của các ID và epoch trên làm AAD. Signed grant bind thêm grantor key ID và envelope bytes; dùng canonical signature profile đã review. Verifier xác thực directory, grant, identity/scope/epoch và version trước unwrap. HPKE base không tự xác thực sender. Chữ ký grant/manifest và key directory tách vai trò đó. Không serialize private keys hoặc clear DEK vào API, database, logs hay web storage.

## 12. Multipart, retry và resume

1. Server kiểm quyền, quota và policy rồi cấp intent chứa IDs bất biến, expected ciphertext size và target revision. Client dùng worker tạo sealed spool ciphertext trong OPFS hoặc vùng tạm có hỗ trợ, đồng thời hash stream. Giới hạn bộ nhớ theo chunk/buffers và số part đang gửi. Nếu nền tảng không giữ được spool an toàn, tắt resume qua restart trên nền tảng đó và mở intent/DEK mới khi phải mã hóa lại.
2. Sau khi spool đủ byte và có digest, bind một lần manifest, chữ ký và envelopes, rồi mới mở S3 multipart. Giữ part transport khoảng 8 MiB của đường hiện tại. Slice theo ciphertext byte offsets độc lập với crypto record, part có thể cắt giữa record. Tôn trọng giới hạn provider như S3 part tối thiểu 5 MiB trừ part cuối, cùng max part/count và checksum header khi ký. [S3 multipart limits](https://docs.aws.amazon.com/AmazonS3/latest/userguide/qfacts.html) · [Client hiện tại](../frontend/components/drive/upload-service.ts).
3. Retry mạng gửi đúng sealed bytes của part cũ. Đối chiếu receipt, part index/length, digest/checksum hiện có và ListParts. Trước resume, kiểm digest/sealed state cùng scope/intent. Local file thay đổi không được thay thế bytes của intent cũ. Nếu spool thiếu/khác digest, journal không chắc đã persist, storage quota cạn hoặc mất quyền thì dừng intent cũ theo abort/expiry và mở attempt với IDs/DEK mới nếu vẫn được phép. Reload không re-encrypt chunk từ file được chọn lại dưới nonce cũ.
4. Worker verify toàn bộ staging ciphertext, copy/pin exact version và commit theo P5. Resume sau COMMIT failure giữ staging và idempotency payload đã bind. FileVersion publish chỉ sau verify khách quan tại server, quota/audit được ghi một lần. Client đang chờ phải phân biệt pending, retry và terminal failure theo contract hiện có.

## 13. Đề xuất API, schema, integrity và quota

Tên dưới đây là contract đề xuất. Dùng route/version rõ để client cũ tiếp tục hoạt động và thao tác CSE không rơi sang legacy path khi capability/policy chưa đạt.

| Contract | Dữ liệu và guard |
| --- | --- |
| Upload init và manifest bind | Mở intent idempotent với format, plaintext size, scope và preallocated crypto IDs. Bind digest, manifest prefix, producer signature, device/grant epoch và initial envelopes đúng một lần trước ký part. Payload khác cùng key bị từ chối. TTL/cancel/expiry tiếp tục dùng reservation lifecycle của P5. |
| UploadSession và FileVersion | Additive metadata theo discriminator riêng như `legacy_aes`, `plain`, `cse_v1`. Lưu immutable crypto IDs, sizes, digest ciphertext, format/header, producer key ID/signature, policy snapshot và lifecycle state. Không suy format từ `is_encrypted` một mình. Ràng buộc Tenant/Workspace, IDs unique và payload đã bind. |
| StorageLocation | VersionId và connection revision đã pin, physical ciphertext bytes/digest và provider checksum typed. Chỉ cấp signed GET đúng authorized version. Dùng receipt recovery của P5 cho object versions còn dư. |
| Directory và device enrolment | Fetch signed public record/key epoch theo scope. API challenge, approval và revoke có step-up, idempotency, scope check và audit. Đổi key tạo revision mới, không ghi đè public key đã dùng. |
| Envelopes và grants | Bản ghi `VersionEnvelope` gắn FileVersion, Tenant, recipient key-purpose, grant/policy epoch. Unique theo version/key/epoch, foreign key phạm vi và traversal từ ACL. Chỉ trả envelope của recipient/device đủ quyền. Kiểm quyền lại lúc commit share/recovery, giới hạn batch để tránh lộ directory hoặc tăng quota bất thường. |
| Download và audit | API trả descriptor, attestation/envelope theo current grant và signed URL ngắn hạn. Tái dùng can-view/RBAC và kiểm device state riêng. Audit sự kiện authorization/rewrap/recovery/revoke theo actor và version, HTTP GET được cấp URL không tự chứng minh plaintext đã đọc. |

| Trường | Ai xác minh và ý nghĩa |
| --- | --- |
| `plaintext_sha256` | Client tính và đối chiếu sau khi giải mã. Giữ trong encrypted manifest, tránh dùng làm plaintext index/log. |
| `ciphertext_sha256` | Django stream hash toàn bộ ciphertext thực nhận với digest đã bind có chữ ký. Client cũng đối chiếu qua download. Bằng chứng plaintext phụ thuộc giải mã và tag. |
| `provider_checksum` | Giá trị typed gồm thuật toán, loại full/composite/part và receipt. ETag dùng đúng ngữ nghĩa conditional copy/receipt. [S3 integrity](https://docs.aws.amazon.com/AmazonS3/latest/userguide/checking-object-integrity-upload.html) |
| `authenticated_manifest` | Client verify AEAD. Django xác minh envelope/prefix đúng cấu trúc, device signature và digest ciphertext trong phạm vi quyền. Trạng thái ciphertext đã được kiểm ở server, client đã decrypt và scanner policy có ba ngữ nghĩa khác nhau. |

Khuyến nghị quota nghiệp vụ tính logical plaintext size đã khai báo có ràng buộc cấu trúc. Tính `152 + P + 16*N` trên server, enforce P tối đa 100 MiB theo [validator hiện tại](../backend/files/validators.py), N/chunk profile và ciphertext thực tế. File tối đa ở profile này có 104.859.352 bytes wire. Admission giữ reservation logical và kiểm giới hạn wire. Chốt logical quota theo ciphertext envelope hợp lệ cùng policy, source scope giữ Personal-Tenant, Enterprise Tenant + Member, Collaborative Workspace như P5. Đo physical bytes riêng, gồm staging, overhead, versions, quarantine, delete markers và bản dư sau retry. Dùng cap dung lượng physical và telemetry cho vận hành, không silently đổi công thức quota hoặc thanh toán. Storage usage và giá trị nghiệp vụ có reconciliation riêng. [Quota hiện hành](../backend/files/quota.py).

## 14. Sharing, revocation và offboarding

- Share CSE v1 yêu cầu owner/collaborator có quyền chia sẻ và có DEK, xác thực key recipient qua directory và cấp envelope cho từng device được duyệt. Commit ACL và envelopes tương ứng idempotent, có kiểm lại scope/epoch. Grant đã duyệt nhưng còn thiếu envelope hiển thị chờ cấp key. Đọc folder theo ACL hiện có vẫn cần envelope từng version, không phát khóa toàn thư mục theo mặc định.
- Public link, guest, cross-Tenant share và move liên Workspace đề xuất tắt với CSE v1 cho tới khi có mô hình trust/capability riêng được duyệt. Tránh đưa DEK vào URL hoặc log. Chia sẻ nội bộ trước dùng Tenant và Workspace đã duyệt đúng policy.
- Revoke chặn cấp mới URL và envelope, invalidate grant/device epoch, vẫn giữ audit. URL cũ có TTL và dữ liệu tải trước vẫn có thể được dùng. Rotate key cho version mới. Nếu policy cần loại thiết bị cũ khỏi dữ liệu còn tồn tại, re-encrypt thành version mới và xử lý lịch sử/retention có approval. Rewrap cùng DEK không vô hiệu DEK đã được tải.
- Offboard thu hồi membership, app sessions theo contract, managed device/grant và quyền nhận envelope mới. Giữ nội dung Organization trong đúng Tenant/binding. Custodian chỉ dùng Enterprise recovery đã duyệt. Không chuyển quyền đọc sang Platform/Org Admin tự động.

## 15. Download, scanner và tính năng dựa vào plaintext

| Tính năng | Compatibility proposal |
| --- | --- |
| Download và versioning | Browser fetch signed exact version, verify descriptor/GCM và xuất file. Undo metadata như rename/Trash không đổi AAD. Restore một version lịch sử phải xác minh ACL/attestation và pin lại đúng đối tượng theo policy. Fail-closed nếu decoder, key hoặc format thiếu. |
| Preview, thumbnail, MIME | CSE đi qua reader client riêng. Dùng allowlist format/size và sandbox khác origin không cấp script/capability cho nội dung active. Thumbnail phía client nếu có phải được bọc key theo cùng ACL/retention hoặc tắt ban đầu. MIME khai báo chỉ là hint ở server. |
| Search và ZIP | Search metadata hiện có. Content indexing trên server hoãn. ZIP tạo client-side trên file đã verify, giới hạn kích thước/số mục và sanitize tên. Server ZIP/preview CSE trả capability không hỗ trợ cho đến khi có client reader. Giữ đường legacy đã có. |
| Malware scanning | Server thông thường có ciphertext và trạng thái policy. Local client scan là best-effort, flag tự khai như `client_scan_passed` không là bằng chứng. Endpoint scanning do Organization quản lý tăng tín hiệu, phụ thuộc chất lượng attestation và posture của thiết bị. Delegated scanning cho phép một principal riêng giải mã scope hạn chế, phải có consent/policy, keys ngắn hạn, audit/retention và đánh đổi confidentiality. Tenant yêu cầu scan tin cậy chọn chế độ được duyệt hoặc giữ encrypted file ngoài trạng thái có thể tải. |
| Audit và backup/restore | Audit cấp quyền, giải mã được ủy quyền và policy decision theo actor/scope, với sự kiện client ghi rõ nguồn. Backup ciphertext, signed manifests, grants, key epochs/bindings và kho backup recovery độc lập. Restore xác minh đúng scope, exact version và đọc qua authorized device/recovery fixture. |
| Mất key | UI phân biệt mất quyền với thiếu envelope/kit; quyền quản trị reset không giải quyết được trường hợp mất authority giải mã cuối cùng. |

Đối chiếu compatibility ở [download/preview](../backend/files/views.py), [direct share API](../backend/sharing/api_views.py) và [ZIP chia sẻ](../backend/sharing/views.py). Hook scanner hiện tại đọc plaintext và tiếp tục phục vụ các luồng legacy trong phạm vi chính sách.

## 16. Rollout, migration và rollback

- Thiết kế schema additive, constraint để per-format metadata đầy đủ. Giữ IDs legacy và reader cũ. Metadata migration nếu có chỉ phân loại version từ bằng chứng đã kiểm, flag riêng. Không rekey, đổi binding hoặc migrate bytes ngầm. CSE available đòi manifest, actual ciphertext digest và required envelopes cùng scope trong transaction publication.
- Thêm dual reader và check capability trước encrypted writer. Qualification bắt đầu bằng fixture có scope, reader/preview/share/recovery checks, rollout opt-in theo Tenant/Workspace và policy. Nếu tenant bắt buộc CSE, client thiếu khả năng ghi nhận lỗi rõ hoặc chỉ đọc, tránh silent plaintext fallback.
- Rollback ưu tiên dừng encrypted writes, giữ CSE reader, directory và recovery keys đủ đọc file đã tạo. Nếu CSE writer có lỗi, forward-fix hoặc chặn đúng feature theo policy. Dữ liệu đã tạo luôn cần một đường đọc đã xác minh. Schema reverse chỉ sau khi backup và chứng minh không còn reference CSE/intent đang dùng. Restore thử cả legacy và CSE đúng revision, exact version và key epoch.
- Quy trình backup tách custody recovery keys khỏi bundle app/SeaweedFS. Consistency point gồm writers, pending upload/recovery/grant, key generation và revocation checkpoint. Khôi phục vào fixture khác. Thử mất một loại backup, phục hồi có quorum và chống reintroduce directory/grant đã thu hồi.

## 17. Test specification trước implementation

**NOT RUN.** Gate được ghi theo exact commit, browser/version, fixture và test mode. PostgreSQL isolation, mock fault, real outage và real provider được báo riêng theo [storage validation skill](../.agents/skills/bluedrive-storage-validation/SKILL.md).

| Nhóm | Ca bắt buộc và assertion |
| --- | --- |
| Known-answer và interoperability | Vectors NIST GCM, RFC 9180, P-256 signature/trust encoding, AES-GCM và KDF vectors cho lựa chọn đã chốt. So output byte-for-byte từ browser/runtime và độc lập bằng implementation tham chiếu. |
| Format và tamper | Round-trip rỗng, 1 byte, biên chunk và file lớn. Sai key, tag, AAD, ciphertext, manifest, signature, scope, file/version ID. Truncate, extra/trailing bytes, duplicate, thiếu, reorder và thay chunk khác file. Reject trước export và kiểm parser allocation với header độc hại. |
| Nonce và resume | Property test không trùng nonce theo DEK, index manifest dành riêng và giới hạn counter. Mạng retry dùng đúng bytes, file local thay đổi, crash giữa encrypt/seal, crash sau seal, spool hash sai, concurrent hai tab, abort và expiry. Luồng ambiguity dùng DEK/version mới. |
| Browser và bộ nhớ | Chromium, Firefox, Safari/iOS, mobile tối thiểu được duyệt. Secure context, key persistence/unlock after relaunch, OPFS quota/clear, RAM worker bounded và unsupported fallback an toàn. Xác nhận multi-part boundaries qua browser CORS thật. |
| Device và key directory | Enrollment, proof sai/expired, user-session only, revoke, rotation, wrong passphrase, reset login, key ID substitution, scope mismatch, directory rollback, first-contact verify. Signed grants và historical keys xử lý đúng. |
| Recovery và offboarding | Lost device có/thiếu kit, sai kit, mất recovery material, cross-Tenant key isolation, Org Admin mặc định deny, quy trình quorum sai/đủ/expires/replay, custodian khác Tenant, recovery audit, rewrap đúng version và offboarding giữa publication/share. |
| Storage và lifecycle | Browser encrypt → SeaweedFS ciphertext, finalizer verify và signed GET pinned → browser decrypt. Retry, lỗi PostgreSQL COMMIT, stale worker, Gateway/Filer outage, version pinning, quota logic/physical reconciliation, purge/delete/restore, Enterprise binding isolation và cleanup theo receipt. |
| Compatibility và restore | Legacy AES reader, plaintext reader, inline/ZIP/sharing policy, malware state fail-closed cho Tenant yêu cầu scan, backup/restore ciphertext và key metadata với scopes/epochs đúng, hồi phục key độc lập, authorization decline chéo Tenant. |

Trước khi bắt đầu rollout, lặp các gate P4/P5 mà implementation chạm tới, gồm real SeaweedFS, browser, PostgreSQL, outage và backup/restore theo contract mới. Không chuyển provider SKIP thành PASS.

## 18. Quyết định bảo mật cần phê duyệt

| Gate | Cần chốt trước khi viết đường production |
| --- | --- |
| Trust model và feature coverage | Ranh giới compromise Django với client origin/bundle, trust bootstrap và independent anchor/epoch. Phạm vi đảm bảo rollback, nhất là thiết bị mới và restore backup. Browser/device tối thiểu. |
| Device custody và KDF | P-256/HPKE library sau security review và interop, format signature/envelope canonical, cách local unlock/hardware, kit UX, KDF/memory profile đã benchmark. Dependency runtime cần duyệt riêng. |
| Enterprise policy | Ai giữ khóa/có quyền yêu cầu, duyệt, nhận, quorum khi thiếu người và lịch rotate/retire. Dữ liệu Employee My Drive retained, jurisdiction, recovery audit và consent/notification. Tách Personal và Organization recovery. |
| Product và integrity | Metadata lộ ở mức nào, malware policy cho từng Tenant, preview/ZIP rollout, share/public link/move scope, revocation và lịch xử lý version cũ. Công thức quota logical và giới hạn/cost physical. |
| Rollout/rollback | CSE-required policy tránh downgrade, điều kiện disable writer, reader/S3/version/key continuity, audit owner, approved fixture, backup/restore rehearsal và release gates. |

## 19. Thứ tự triển khai đề xuất

1. Review độc lập threat model, key custody, recovery, scope Tenant và policy product. Chốt browser/interop matrix và negotiation phiên bản.
2. Chạy capability và benchmark fixture cho WebCrypto, HPKE candidates, OPFS và KDF. Chốt format/envelope bằng vectors hai implementation, đo memory và kiểm review nguồn. Phê duyệt dependency cần thiết.
3. Dựng reader/encoder thử nghiệm và trust/enrollment/recovery primitives trên fixture, cùng negative vectors. Reader legacy tiếp tục qua suite tương thích trước khi thêm writer.
4. Thêm contract additive, ciphertext publication và quota trong fixture, rồi sharing/revoke/recovery. Kiểm lifecycle P4/P5 đã thay, audit và backup/restore. Đo cả failure/cancel và route pin.
5. Sau security review và phê duyệt vận hành, thử opt-in hẹp, có rollback đọc được version CSE và runbook recovery có custodian. Kết luận P6 SECURITY ACCEPTED chỉ sau khi các quyết định và gates theo môi trường đã đạt.

## 20. Findings từ prototype P6.1

- Suite P-256 thử với `@hpke/core` cần truyền `CryptoKeyPair` gồm public key khớp với directory và private key non-extractable khi mở envelope. Truyền riêng private key làm thư viện thử export để tái tạo public key và thất bại. Prototype giữ các byte format `cse_v1`.
- Xác thực receipt resume với scope và chữ ký producer đã pin cùng digest của spool. Digest do người chỉnh được cả spool và receipt cung cấp không đủ bằng chứng. Nếu receipt không xác thực được, bỏ intent cũ và dùng version/DEK mới.
- Non-extractable `CryptoKey` trong IndexedDB vẫn dùng được từ cùng origin khi UI fixture đang khóa. Bản sao Chrome profile trên cùng máy Windows cũng dùng được key. Khi yêu cầu khóa thực sự ngoài phiên, cần chốt trust boundary độc lập, chẳng hạn origin/client tách riêng hoặc authenticator có unlock đã kiểm chứng.
- Một authority fingerprint đã pin xác thực nguồn chữ ký. Thiết bị mới vẫn cần checkpoint đáng tin để biết directory mới nhất. TOFU hoặc chỉ xác minh chữ ký đều có thể chấp nhận epoch cũ khi thiếu checkpoint.
- OPFS resume cần qualification riêng theo engine/OS. Fixture WebKit Windows xác minh crypto và IndexedDB nhưng probe OPFS trả `UnknownError`. V1 nên chặn resume khi capability chưa đạt. Enterprise prototype xác minh hai phê duyệt độc lập trước một service giữ khóa. Cryptographic threshold custody vẫn là quyết định mở.

[Kết quả, phạm vi browser và các quyết định cần duyệt](REFACTOR_P6_CRYPTO_FEASIBILITY_2026-11-19.md).
