# BlueDrive — review Platform SeaweedFS và chuẩn bị cutover

Ngày kiểm tra chính: **12/11/2026**, bổ sung hoàn thiện **13/11/2026**, Asia/Bangkok. Báo cáo phân biệt source đã sửa, test đã chạy và dữ liệu/routing thật. **Chưa chuyển 31 FileVersion; chưa đổi endpoint/binding/flag và chưa dừng MinIO.** Không commit/push.

## A. Hiện trạng trước thay đổi

Git ban đầu có **253 status entries, 212 file untracked**. Các thay đổi đó được giữ, không reset/stash/stage; diff so với HEAD bao gồm công việc trước phiên này. Không coi toàn bộ diff là phần mới của báo cáo.

Kiểm kê DB/S3 mới trong phiên:

| Hạng mục | Giá trị đã xác minh |
| --- | --- |
| File / FileVersion / StorageLocation MinIO | 31 / 31 / 31 |
| Bytes logical/source đã đối chiếu | 5.693.666 |
| Source SHA-256 khớp FileVersion | 31/31 |
| Local legacy media đang tham chiếu | 0 |
| Config MinIO active | 4 |
| UploadSession | 48 available, 6 failed, 4 canceled |
| Session ghim revision / đang nhận upload | 0 / 0 |
| Session legacy còn cleanup references | 48 |
| Finalization job | 46 done |
| Reservation | 48 consumed, 6 released, 0 reserved |
| Tenant / Workspace / QuotaAccount | 5 / 19 / 19 |
| Share / ActivityLog | 2 / 242 |
| Ready Platform S3 revision đủ điều kiện | 0 |
| Source object versions / staging versions | 31 / 0 |
| Unreferenced candidates trong LIST hiện có | 0; không phải quyền xóa |
| Multipart còn treo | **0 theo operator snapshot 12/11**; audit app ngày 13/11 vẫn Unknown do bị từ chối |

Kiểm kê lại ngày 13/11 xác nhận 31/31 bytes/hash và các số DB trên không đổi. Manifest exact IDs/key/version hiện tại nằm trong `infra/seaweedfs/.local/cutover-final-inventory-20261113.json`, được ignore. Audit app ghi multipart Unknown đúng theo quyền; evidence operator trong backup giữ kết quả 0 tại snapshot 12/11. Cần LIST operator và inventory lại sau khi đóng băng writer, không coi hai snapshot là cùng thời điểm. Không sao chép key/config private vào báo cáo.

Nguồn sự thật của từng chức năng:

| Trách nhiệm | Source hiện tại |
| --- | --- |
| User/Tenant/Workspace và RBAC | `accounts/access.py`, membership models; sharing policy/services |
| Session/quota/storage target | `files/upload_api.py`, `quota.py`, `storage_routing.py` |
| Bytes/checksum/publication | `finalize_uploads` + `files/finalization.py` + adapter S3 |
| Download/preview/sharing/ZIP | `files/views.py`, sharing services, `folders/archive_service.py` |
| Trash/restore/permanent delete | Files/folders views và `files/permanent_delete.py` |
| Routing/revision/profile | Infrastructure models, connection services và PostgreSQL triggers |
| Client upload/resume/download | Frontend upload services/UploadManager, drive/account/share/workspace services |
| Storage runtime | Platform Compose/runbook; Enterprise Compose độc lập; container thực tế |

Rủi ro đã sửa: fallback legacy có thể dùng kho global mới; cache delete bỏ qua kiểm endpoint ở config thứ hai; folder upload legacy có thể bỏ qua routing; probe báo PASS sau cleanup lỗi; harness Windows không phân giải `s3.localhost`; Chrome harness cần Local Network Access; persistence cleanup có thể đụng version ngoài fixture; trigger publication không cho tháo lịch sử upload đã xóa file.

## B. Triển khai và phân loại

| Phân loại | Thành phần | Lý do |
| --- | --- | --- |
| KEEP | Một adapter S3, finalizer Django riêng process, quota/access/sharing services | Đã có contract chung, không thêm adapter SeaweedFS trùng |
| KEEP | AES reader/key, enum/migrations/config/compose/tests MinIO | Còn nguồn thật, cleanup references và rollback; chưa có bằng chứng được gỡ |
| MODIFY | Resolver legacy, delete cache, folder upload guard | Chặn đọc/ghi/xóa nhầm kho và bypass target |
| MODIFY | Adapter PUT metadata, probe command, integration/browser/persistence harness | Giữ metadata/checksum; fail khi cleanup lỗi; kiểm provider thật đúng host/version |
| ADD | Manifest migration/service/command và regression | Copy/retry/verify, append-only publication, rollback; không xóa nguồn |
| MODIFY | Nhãn/comment storage frontend/backend, tài liệu hiện hành | Phản ánh adapter S3 chung và trạng thái chưa cutover |
| MERGE | Không có ứng viên đủ bằng chứng | Các lớp hiện tại có trách nhiệm riêng; không hợp nhất hình thức |
| REMOVE | Không xóa source/test/dependency nào trong phiên | Chưa có thành phần được chứng minh hết trách nhiệm; output private/cache tiếp tục ignore |

File **mới trong phiên**:

- `backend/files/storage_cutover.py`
- `backend/files/management/commands/migrate_platform_storage.py`
- `backend/files/tests/test_storage_cutover.py`
- `backend/infrastructure/migrations/0006_allow_deleted_upload_history.py`
- `infra/seaweedfs/test_smoke.py`
- `docs/ADR-0008-platform-storage-copy-and-publication.md`
- Báo cáo này.

File **chỉnh tiếp trên công việc đã có**, kể cả một số file đang untracked từ trước:

| Nhóm | Đường dẫn |
| --- | --- |
| Audit/migration tests | `backend/files/management/commands/audit_storage_cutover.py`, `backend/files/tests/test_storage_cutover_audit.py` |
| Storage/routing | `backend/files/storage_routing.py`, `backend/files/storage_adapters/base.py`, `backend/files/storage_adapters/s3_compatible.py`, `backend/files/permanent_delete.py`, `backend/files/management/commands/check_connections.py` |
| Backend callers/tests | `backend/folders/views.py`, `backend/folders/archive_service.py`, `backend/dashboard/drive_api.py`, `backend/files/tests/test_storage_adapter.py`, `backend/files/tests/test_workspace_access.py`, `backend/files/tests/test_download_security.py`, `backend/infrastructure/test_storage_routing.py`, `backend/files/tests/test_seaweedfs_integration.py` |
| Infra harness | `infra/seaweedfs/smoke.py`, `infra/seaweedfs/browser-smoke.mjs`, `infra/seaweedfs/README.md` |
| Frontend services | `frontend/components/drive/upload-service.ts`, `frontend/components/drive/upload-resume-model.ts`, `frontend/lib/drive-service.ts` |
| Frontend nhãn admin | `frontend/components/admin/PlatformDashboard.tsx`, `frontend/components/admin/InfrastructureDetail.tsx`, `frontend/app/(admin)/admin/infrastructure/page.tsx`, `frontend/app/(admin)/admin/infrastructure/topology/page.tsx`, `frontend/app/(admin)/admin/backups/policies/page.tsx` |
| Frontend docs/tests | `frontend/README.md`, `frontend/e2e/admin.spec.ts`, `frontend/e2e/admin-business.spec.ts` |
| Ngữ cảnh/config mẫu | `README.md`, `MAP.md`, `backend/README.md`, `backend/.env.example`, `docs/DEVELOPMENT.md`, `docs/MINIO_STORAGE_ADAPTER.md` |

Không thêm dependency. Sáu dependency runtime frontend đều có caller; dependency backend gồm cả dependency bắc cầu của Django/DRF/crypto/S3/PostgreSQL, không gỡ chỉ vì không có import trực tiếp. Không sửa private endpoint/credential/key. ADR-0008 và runbook giữ một workflow cutover, không nhân bản lệnh trong nhiều tài liệu.

## C. Storage runtime

| Môi trường | Trạng thái thực tế |
| --- | --- |
| Platform SeaweedFS | 4.53; PostgreSQL Filer 17.11; 5 service healthy; chỉ S3 loopback `:8333`; role/schema/network/volume riêng đã kiểm tra |
| Enterprise Lab | Giữ S3 `:8433`; container ID/mount/StartedAt không đổi |
| MinIO | Nguồn vẫn chạy `:9000–9001`; không stop, delete object hoặc xóa volume |
| Cutover | **CHƯA THỰC HIỆN**; global/routing/binding giữ nguyên |
| FileVersion source đã đối chiếu bytes | **31/31** |
| FileVersion đã copy/publish vào storage chính mới | **0/31** |

Persistence mới: restart đúng 5 service Platform không recreate, ID/mount giữ nguyên; sáu container Enterprise/MinIO không đổi thời điểm khởi động. Fingerprint **16 hàng metadata bucket** và hash 10 config private giữ nguyên. Probe 38 bytes giữ đúng Version ID và full SHA-256 `30b27ee8265df57ed282b618758dc4653c576c7566ff1e1e572281bce0d88f93`. Cleanup chỉ xóa exact version fixture mới, HEAD pinned trả 404; probe lịch sử được giữ. Evidence private: `.local/persistence-gate-c465ec5aea0f4c7386b8803681f1f30a.json`.

## D. Kiểm thử

Các lệnh Python dùng `.venv/Scripts/python.exe` 3.12.10. Sandbox launcher cần escalation để truy cập interpreter per-user; process dev đặt `DEBUG=true`, không sửa `.env` hoặc hạ bảo vệ production. Kết quả ban đầu lỗi do môi trường/fixture đã được sửa và chạy lại, không được tính PASS trước khi có lần chạy đạt.

| Lệnh / gate | Bằng chứng lần chạy này | Trạng thái |
| --- | --- | --- |
| `backend/manage.py check` | 0 issues | **PASS** |
| `backend/manage.py makemigrations --check --dry-run` | No changes detected | **PASS** |
| `infra/seaweedfs/regression.py` | 601 discovered, **582 PASS/19 SKIP**, 0 fail, 939,071 giây; trước trigger cuối | **PASS regression**, không đóng gate bị skip |
| Regression liên quan sau sửa cuối, opt-in SeaweedFS (13/11) | **106/106 PASS**, 0 skip/fail, 41,526 giây; DB test mới áp dụng migration 0006; gồm nguồn thiếu VersionId và chống corruption/receipt giả | **PASS** |
| Unit adapter/routing/probe không DB | 40 tests, 0 fail/skip | **PASS** |
| `unittest discover -s infra/seaweedfs -p 'test_*.py'` | 7 tests, 0 fail/skip | **PASS** |
| Enterprise generator compatibility | 2 tests, 0 fail/skip | **PASS** |
| `smoke.py test`, opt-in fixture riêng | 8 provider tests, 0 fail/skip; Create/Put/Get/Head/Delete/range, multipart/resume/abort, presign dương/âm, SHA/checksum, conditional copy, version pin, deny anonymous/credential/cross-bucket | **PASS** |
| `smoke.py browser` | Chrome thật PUT/GET/CORS/ETag/checksum/bytes | **PASS** |
| `seed-restart` → exact Platform restart → `verify-restart` | 11 assertions; cleanup pinned fixture thành công | **PASS** |
| Worker thật trên DB test riêng (thuộc 106 bài cuối) | **2/2 PASS**: file thường/file rỗng publish/download/quota, SHA-256 sai không publish và release reservation | **PASS** |
| `npm.cmd run lint` | ESLint | **PASS** |
| `npx.cmd tsc --noEmit` | TypeScript | **PASS** |
| Full Node: 39 file `*.test.mts` | 159 tests, 0 fail/skip | **PASS** |
| `npm.cmd run build` | Next 16.3.3, 39 static pages; retry với quyền tải Poppins sau lỗi mạng | **PASS** |
| 9 mocked Playwright specs, desktop/mobile | 212 tests, 0 fail/skip/flaky; 106 mỗi viewport | **PASS** |
| Impeccable detector/render desktop/mobile | `[]`, nhãn storage và trạng thái Unknown hiển thị đúng | **PASS** |
| Repository safety + self-tests | 632 text files, 1 binary chưa scan, 0 findings; 13 self-tests PASS | **PASS** |
| Final whitespace/link/diff check | Local links/path, file mới/untracked, Python AST và `git diff --check` đạt | **PASS** |
| Live app My Drive/Personal Workspace/sharing/quota/audit sau cutover | Chưa có serving target/approved dedicated account; mocked tests không thay thế | **BLOCKED** |
| MinIO-specific optional integration | Không bật ghi/xóa fixture trên nguồn đang dùng | **SKIP** |

Mocked browser command: `npx.cmd playwright test mocked.spec.ts download.spec.ts upload-publication.spec.ts storage-connections.spec.ts storage-topology.spec.ts storage-monitoring.spec.ts admin-business.spec.ts storage-plans.spec.ts system-review.spec.ts`. Server UI tạm đã dừng, không dừng dịch vụ có sẵn. Evidence generated được ignore tại `frontend/test-results/results.json`.

Lượt backend cuối nạp `infra/seaweedfs/.env` trong process riêng, đặt `SEAWEEDFS_INTEGRATION=1`/`SEAWEEDFS_ALLOW_TEST_WRITES=1`, rồi chạy runner với labels: `files.tests.test_storage_cutover`, `files.tests.test_storage_cutover_audit`, `infrastructure.test_storage_routing`, `files.tests.test_download_security`, `files.tests.test_workspace_access`, `files.tests.test_storage_adapter`, `files.tests.test_seaweedfs_integration`, `files.tests.test_seaweedfs_finalizer_integration`. 106 bài gồm toàn bộ regression mới và 12 bài HTTP/provider/worker thật/helper; log checksum failure của case âm là hành vi mong đợi. Lượt 103/103 trước đó đã đạt, sau sửa nguồn legacy chạy lại thành 106/106. Không cộng các lượt thành số test duy nhất vì có bài chạy lại. Tất cả fixture của gate đã dọn theo namespace riêng.

Kiểm kê tests source: backend có 63 file test tại thời điểm kiểm kê (accounts 23, files 18, dashboard 8, infrastructure 7, sharing 4, folders/security/tools mỗi nhóm 1), frontend 39 Node files và 13 E2E specs. **KEEP** các test business/auth/RBAC/isolation/upload/download/quota/sharing/recovery; **UPDATE** provider copy/harness; **ADD** case integrity/rollback/cleanup mới. Không MERGE/REMOVE vì chưa chứng minh assertion trùng trách nhiệm hoặc feature đã bỏ. Số file/source không phải số bài đã thực thi.

## E. Bảo mật, dữ liệu và rollback

Command migration không nhận endpoint/secret từ browser, chỉ dùng revision Platform verified. Manifest hash ghim DB/source/target và key namespace; approval ghim hành động/evidence. Lệnh ghi không chạy trong phiên. Copy đọc version nguồn, tính SHA-256 toàn file, giữ metadata và đọc lại version đích. Publish thêm location, không update source identity, không tạo FileVersion hoặc tính thêm quota. Rollback chuyển target location về pending sau khi kiểm nguồn; vẫn cần giữ reader revision cho file mới đã ghi vào SeaweedFS sau cutover.

Migration additive `infrastructure.0006_allow_deleted_upload_history` chỉ được áp dụng trên DB test trong phiên. Trước khi dùng permanent-delete của code mới, operator phải triển khai migration này theo checkpoint đã duyệt: chỉ cho gỡ FK của successful upload sau khi hết FileVersion cũ, giữ target bất biến và cấm reattach/insert công bố rỗng. Sau khi có history đã tháo FK, không reverse về trigger cũ vì cleanup lịch sử sẽ bị chặn; ưu tiên forward-fix.

Các lỗi key contract, receipt ghi đè source version pin, latest legacy đổi, target disabled khi rollback, location cạnh tranh và JSON sai kiểu được review độc lập và bổ sung test. Audit phân biệt ciphertext đã hash với ciphertext đã có bằng chứng, không chứng nhận nội dung từ trọng lượng/ETag.

Backup private: `backups/platform-cutover-20261112-8f5de27c-verified/`, Git ignored; ACL giới hạn current user/SYSTEM/Administrators.

| Backup/restore gate | Kết quả |
| --- | --- |
| PostgreSQL 18.6 custom dump | **PASS**, 313.998 bytes; SHA-256 `543b8714c5dd816c435e0a32f21f7a672069c460bc682c8898c6e129ab2e7609` |
| Restore DB mới cách ly | **PASS**, 51 bảng/977 hàng, toàn bộ row fingerprints khớp |
| Constraint/trigger | **PASS**, 688 constraints; 27 CHECK được canonical round-trip bằng PostgreSQL trên DB test để so khác biệt cast syntax, không bỏ assertion; custom triggers khớp |
| Dọn DB restore | **PASS**, chỉ DB ngẫu nhiên do tác vụ tạo; không restore đè DB ứng dụng |
| Key/config legacy | **PASS**, 642 file/163.857 bytes, disk hashes và AES runtime key khớp |
| Object bytes/metadata/version mapping | **PASS** 31 versions/5.693.666 bytes; disk SHA-256 khớp; coverage 31/31; inventory trước/sau ổn định |
| Object tags/bucket config/multipart inventory | **PASS bằng operator hiện có**: 31/31 version có tags rỗng; 5 API bucket config đã kiểm, 4 cấu hình vắng được xác nhận rõ; versioning Enabled, 0 multipart; không đổi ACL app |
| Phục hồi object backup vào bucket S3 cách ly mới | **PASS 31/31**: GET ghim version mới khớp bytes/SHA-256/user/header metadata/tags; anonymous và application identity đều 403; exact-version fixture cleanup và bucket HEAD 404 |

Evidence sanitized trong backup: `final-backup-summary.json`, `reference-coverage.json`, `metadata-permission-evidence.json`, `operator-metadata-summary.json`, `verified-backup-summary.json`. Evidence app AccessDenied được giữ như lịch sử, kết quả operator bổ sung đóng gate metadata. Credential operator chỉ dùng trong bộ nhớ, không in hoặc lưu thêm vào backup. Bản dump đầu chưa đạt đối chiếu CHECK còn giữ tại thư mục cùng tiền tố không có `-verified`; không xóa evidence. DB snapshot và object backup chưa phải snapshot chung sau khi đóng băng ghi, cần lặp inventory cuối trong cửa sổ cutover.

Bằng chứng recovery cuối là `recovery-verified-backup-summary.json` và `s3-restore-summary.json`. Bucket fixture mới `bluedrive-restore-8178c7a53c274f2789b4aea255ec0786` được xác minh chưa tồn tại trước khi tạo, tách source/serving bucket; đã dọn đúng 31 VersionId thuộc receipts rồi xóa bucket rỗng. Không publication hoặc sửa source reference. Backup hiện ở local, chưa kiểm chứng độ bền off-host; diễn tập này không chứng nhận recovery toàn cluster/HA.

Kiểm tra cuối phát hiện cả 31 source HEAD không trả VersionId và DB chưa có version pin. Đây là nguồn plaintext legacy: command chuẩn hóa trường hợp này thành `source_version="null"`, đọc nguồn hiện tại và bắt buộc full SHA-256/kích thước khớp FileVersion tin cậy tại copy/publish/rollback. Chỉ số null không được coi là bằng chứng bất biến; writer phải dừng, target vẫn cần version thật, encrypted source chưa ghim vẫn bị chặn. Rollback không tin receipt thay cho SHA-256 DB. Giống kiện hàng cũ chưa có mã vận đơn, phải đối chiếu niêm phong/nội dung trước khi lập vận đơn mới. Tham khảo [S3 về object tồn tại trước khi bật versioning](https://docs.aws.amazon.com/AmazonS3/latest/userguide/manage-objects-versioned-bucket.html).

## F. Final codebase review và checkpoint

MinIO enum/migration/compose/adapter compatibility, AES reader, legacy media route và frontend compatibility key/route được **giữ có chủ đích**. `/admin/infrastructure/minio` và API `health.minio` chưa đổi để không phá caller; nhãn hiển thị đã trung lập. Source còn được đọc nên không gỡ dependency/config/test chỉ vì có target SeaweedFS.

Trước approval thao tác thật còn cần:

1. Giữ evidence backend/worker/migration theo bảng D; dùng cùng code cho web/worker và áp dụng migration 0006 sau approval trước rollout.
2. Dùng identity operator/reconciler hiện có để kiểm kê cuối multipart/tags/bucket config; không mở rộng quyền runtime app chỉ để test pass.
3. Revision Platform S3 được đăng ký/verified qua quy trình hiện có, không giả ready bằng SQL; lập plan đúng target và digest.
4. Cửa sổ dừng writer/drain/chờ URL hết hạn, inventory cuối và backup/recovery đủ scope, approval manifest/action cụ thể.
5. Xử lý 48 session cleanup references theo nguồn đúng; giữ global MinIO cho đến khi có phương án đã nghiệm thu. Bật binding/routing theo operator, không tự đổi endpoint.
6. Nghiệm thu app live trên SeaweedFS; chỉ sau đó mới review dừng MinIO. Không xóa source/volume trong đề xuất hiện tại.

Workflow chuẩn bị đã có trong skill `bluedrive-storage-validation`; có thể bổ sung phần manifest/backup/restore/approval vào skill đó để dùng lại sau khi checkpoint runtime được nghiệm thu, không tạo skill trùng.

## G. Trạng thái kết luận

| Mốc | Trạng thái |
| --- | --- |
| CODE COMPLETE | **PASS cho phần chuẩn bị code được phép**; công cụ/sửa an toàn đã triển khai và regression cuối đạt; không đồng nghĩa toàn mục tiêu cutover hoàn tất |
| TEST VERIFIED | Từng gate PASS theo D; toàn hệ thống chưa nghiệm thu khi còn BLOCKED |
| RUNTIME CUTOVER COMPLETE | **KHÔNG** |
| DATA MIGRATION VERIFIED | **KHÔNG**; source 31/31 verified, migrated 0/31 |
| MINIO DECOMMISSION READY | **KHÔNG** |
