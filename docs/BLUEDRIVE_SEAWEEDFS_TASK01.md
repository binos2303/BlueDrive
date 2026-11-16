# BlueDrive Task 01 — rà soát và chuẩn bị chuyển SeaweedFS

> Báo cáo lịch sử lượt đầu. Trạng thái và yêu cầu mới nhất nằm trong [bản bàn giao Task 01](BLUEDRIVE_BAN_GIAO_TASK01.md): Docker/Python hiện đã dùng được, Master/Volume đã chạy và người dùng đã cho phép bỏ file test. Các kết quả test dưới đây giữ nguyên theo thời điểm thực hiện.

Ngày: **10/11/2026**, múi giờ Asia/Bangkok. **Trạng thái tổng thể: BLOCKED — chưa nghiệm thu cutover.**

Đã triển khai source/config, sửa backend và chuẩn bị gate kiểm thử thật. Chưa chạy được Docker/SeaweedFS trên máy này; chưa đổi `backend/.env`, chưa dừng MinIO, chưa reset metadata/object. Task 02/03 không thực hiện. Giống như xây và kiểm tra quy trình kho mới: chưa chuyển hàng khi chưa vận hành thử được kho.

## Hiện trạng đã xác minh

- Windows PowerShell 5.1; Node 24.18.0, npm 12.0.2.
- Python yêu cầu 3.12; `.venv` hiện trỏ tới executable Python 3.12.10 đã mất. Đã tải Python 3.12.10 embeddable chính thức vào `.task01-runtime/`, tái dùng dependencies `.venv/Lib/site-packages`, không sửa `.venv` hay cài package runtime mới.
- Django 5.2.17; DRF 3.18.0; boto3/botocore 1.43.112; psycopg 3.3.6; PostgreSQL server 18.6, kết nối local được.
- Next.js 16.3.3, React 19.2.8, TypeScript 5.9.3, Playwright 1.65.0.
- Không tìm thấy Docker executable dùng được trong PATH hoặc vị trí Docker Desktop chuẩn; không chạy được Compose/daemon. WSL enumeration bị Access Denied.
- Đã tải SeaweedFS Windows **4.53** từ release chính thức, đối chiếu SHA-256 theo GitHub release metadata. Windows **Application Control chặn thực thi** `weed.exe`; không tìm cách vượt chính sách.
- Source CLI/config của đúng tag 4.53 đã được đối chiếu upstream. Image tag đã pin, **chưa thể gọi là image đã kiểm thử** hoặc chứng nhận mọi API tương thích.
- Repository ban đầu có nhiều thay đổi chưa commit, gồm routing/storage control center và UI. Đã lưu `task01-evidence/git-status-before.txt`, không reset, checkout hoặc commit công việc có sẵn.

Kiểm kê chỉ đọc DB ứng dụng: **31 file / 5.693.666 byte, 31 version/location ở provider MinIO, 4 storage config MinIO, 58 upload session, 46 finalization job, 19 quota account, 2 sharing reference, 242 audit log; 5 tenant và 19 workspace**. Không có legacy media file trong 31 file này. Không có session pin connection; multi-cluster routing đang tắt. Đây là dữ liệu thật trong DB local; chưa chứng minh toàn bộ file disposable. Chi tiết: `task01-evidence/cutover-inventory.json`.

## Audit đường dữ liệu và quyết định

| Thành phần | Phân loại | Đánh giá / quyết định |
| --- | --- | --- |
| `s3_compatible.py`, boto3, typed errors/retry | KEEP | API chung, không import MinIO SDK; giữ kiểm tra SHA-256, metadata, ETag conditional copy và version-aware delete. Không thêm adapter SeaweedFS trùng lặp. |
| `factory.py`, settings internal/public | MODIFY | Cấu hình global trước đây chỉ cấp public signer khi bật direct-download; upload có thể nhận host nội bộ. Dùng public signer cho upload khi có public endpoint, độc lập cờ direct-download; validate endpoint khi được cấu hình. Không sửa host sau khi ký. |
| `StorageConfig` / `StorageLocation` / `FileVersion` | KEEP | Dùng provider `s3` đã có; không thêm enum/schema/migration. Giữ MinIO enum và lịch sử migration để đọc dữ liệu cũ. |
| Finalizer tạo config mặc định | MODIFY | Ghi provider chung `s3`, tránh tự nhận storage đích là MinIO. Đổi nhãn này không chứng minh endpoint hiện tại đã là SeaweedFS. |
| Upload API / frontend upload service | KEEP | Server tạo key/session, resolve tenant/workspace, kiểm quyền/quota; browser nhận URL tạm, gửi required headers và giữ ETag để resume. Không nhận bucket/endpoint tự do từ frontend. Không đổi UI/protocol frontend. |
| Finalization worker / cleanup | KEEP | Worker hiện có tải spool, băm SHA-256 toàn nội dung, kiểm MIME/scanner, conditional copy rồi publish metadata/quota/audit. Giữ claims/recovery/cleanup; không thực hiện Task 02. |
| Download direct/fallback/preview | KEEP | Direct chỉ cho object đã verified và version pinning; AES legacy/ZIP/preview qua backend; không đổi AES. Không bỏ version guard nếu provider không hỗ trợ. |
| Shared bulk ZIP | MODIFY | Phát hiện đọc trực tiếp FileField AES làm file S3 multipart không đọc được. Chuyển sang `_download_block_reason` và `_decrypt_file` dùng chung, giữ kiểm quyền/hash/version. Đã thêm regression S3 + AES legacy và hash/quyền thất bại. |
| Copy/move/rename/trash/restore/permanent delete | KEEP | Đã truy vết tới adapter và metadata tenant. Giữ mô hình hiện có; không tuyên bố giải quyết rủi ro physical delete trước DB commit. |
| Storage control center / profiles | KEEP / DEFER | Profile hỗ trợ provider `s3`; không dựng UI mới. Telemetry có schema MinIO riêng và fail-closed với provider khác; chưa có collector SeaweedFS, không gán trạng thái healthy giả. Các gate SCC không tự bật. |
| MinIO Compose/runtime cũ | DEFER REMOVE | Chỉ gỡ sau khi SeaweedFS đạt gate và dữ liệu scoped được xác minh/backup. Compose đích mới không chứa MinIO; file cũ được đánh dấu lịch sử/chờ cutover. |
| Reset file thử nghiệm | DEFER | Chỉ thêm command kiểm kê dry-run; không flush DB, không xóa file/location/session/share/quota, không xóa volume. |

So với adapter riêng và thêm provider/schema, phương án dùng adapter S3 hiện tại giữ ít nhánh code và ít migration hơn, đồng thời kiểm tra được cùng contract bảo mật. Đổi kho không cần dựng thêm một hệ thống kiểm hàng riêng cho cùng loại kiện hàng.

Các rủi ro audit cũ được kiểm tra: multipart init đang serialize bằng row lock; worker có attempt/claim fencing; cleanup bỏ qua verifying/scanning; đã có regression permissions/recovery. **Chưa chứng minh bằng SeaweedFS thật** các race/timeout đó. Physical delete vẫn thực hiện trước khi hoàn tất toàn bộ giao dịch metadata ở một số luồng: không sửa hoặc tự nhận đã giải quyết trong lượt này. Shared ZIP đã có sửa và test cụ thể.

## Source/config được tạo hoặc sửa

| Loại | File | Lý do |
| --- | --- | --- |
| Created | `infra/seaweedfs/compose.yml` | Master/Volume/Filer/S3, network riêng, persistent volumes, health checks, loopback S3; pin 4.53. |
| Created | `infra/seaweedfs/.env.example` | Danh mục biến cấu hình, không chứa secret thật. |
| Created | `infra/seaweedfs/configure.py` | Sinh cấu hình private, identity operator/app riêng, PostgreSQL role/database/schema riêng và CORS. Không provision DB tự động. |
| Created | `infra/seaweedfs/test_configure.py` | Kiểm tra auth scope, metadata DB, secret tách biệt, không ghi đè cấu hình, reject wildcard/application DB. |
| Created | `infra/seaweedfs/smoke.py`, `browser-smoke.mjs` | Gate S3 thật, Chrome CORS và restart persistence; credential/URL tạm không in ra log. |
| Created | `infra/seaweedfs/regression.py` | Test DB ngẫu nhiên chưa tồn tại, tránh tái dùng/dọn test DB của người khác. |
| Created | `infra/seaweedfs/README.md` | Runbook PowerShell đầu-cuối, topology, cutover/rollback và production limitations. |
| Created | `backend/files/management/commands/audit_storage_cutover.py` | Kiểm kê chỉ đọc, không có nhánh delete. |
| Created | `backend/files/tests/test_storage_cutover_audit.py` | Xác minh kiểm kê không đổi dữ liệu hoặc cấp phép reset. |
| Created | `backend/files/tests/test_seaweedfs_integration.py` | Contract S3 thật, không mock; opt-in local test writes. |
| Created | `backend/files/tests/test_seaweedfs_finalizer_integration.py` | Upload API → S3 thật → worker hiện tại → download/quota, gồm file rỗng và hash sai. |
| Created | `backend/sharing/test_archive_storage.py` | ZIP mixed S3/AES legacy, version pinning, bad hash và thiếu quyền. |
| Modified | `backend/files/storage_adapters/factory.py` | Chọn public upload signer ở cấu hình global. |
| Modified | `backend/securedrive/settings.py`, `backend/.env.example` | Endpoint public phục vụ upload; validate tách khỏi cờ direct-download. |
| Modified | `backend/files/finalization.py` | Config mặc định provider `s3`; giữ worker/crypto/quota. |
| Modified | `backend/files/tests/test_storage_adapter.py`, `test_finalization_streaming.py` | Regression public/internal signer và generic provider. |
| Modified | `backend/sharing/views.py` | ZIP dùng chung reader và download readiness guard. |
| Modified | `.gitignore` | Bỏ qua binary runtime tạm và config private `.local`. |
| Modified | `README.md`, `backend/README.md`, `backend/minio-compose.yml`, `docs/MINIO_STORAGE_ADAPTER.md` | Dẫn runbook mới, đánh dấu cấu hình/tài liệu MinIO cũ, không tự nhận đã cutover. |
| Created | `docs/BLUEDRIVE_SEAWEEDFS_TASK01.md`, `docs/task01-evidence/` | Báo cáo và bằng chứng kiểm tra. |
| Deleted | Không | Không xóa source, migration, dữ liệu hoặc runtime cũ. |

Đã sinh `infra/seaweedfs/.env` và `.local/{filer.toml,s3.json,cors.json,bootstrap.sql,backend.env}` để sẵn triển khai local; Git ignore đã được xác minh. ACL trên `.env`/`.local` đã giới hạn cho tài khoản hiện tại. Không gửi các file chứa secret cùng báo cáo. SQL và backend env **chưa được áp dụng**.

## Runtime và biến môi trường

Sơ đồ và tất cả lệnh nằm trong [runbook](../infra/seaweedfs/README.md). Mô hình: Browser/Django → S3 gateway → Filer → Volume; Master điều phối, PostgreSQL `seaweedfs_meta` lưu Filer metadata. PostgreSQL app và metadata tách database/role, tái dùng PostgreSQL instance hiện có. Bốn container trên cùng host không phải HA.

Chỉ tên biến, không chứa giá trị secret:

- `FRONTEND_ORIGINS`.
- `FILER_DB_HOST`, `FILER_DB_PORT`, `FILER_DB_NAME`, `FILER_DB_USER`, `FILER_DB_PASSWORD`, `FILER_DB_SSLMODE`.
- `SEAWEED_S3_ENDPOINT`, `SEAWEED_S3_PUBLIC_ENDPOINT`, `SEAWEED_S3_BUCKET`, `SEAWEED_S3_ACCESS_KEY`, `SEAWEED_S3_SECRET_KEY`, `SEAWEED_S3_ADMIN_ACCESS_KEY`, `SEAWEED_S3_ADMIN_SECRET_KEY`.
- Gate: `SEAWEEDFS_ALLOW_TEST_WRITES`, `SEAWEEDFS_INTEGRATION`.
- Django dùng nguồn cấu hình hiện có: `SECUREDRIVE_STORAGE_ENDPOINT_URL`, `SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL`, `SECUREDRIVE_STORAGE_BUCKET`, `SECUREDRIVE_STORAGE_REGION`, `SECUREDRIVE_STORAGE_ADDRESSING_STYLE`, `SECUREDRIVE_STORAGE_ACCESS_KEY_ID`, `SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY`, `SECUREDRIVE_STORAGE_TLS_VERIFY`, `SECUREDRIVE_STORAGE_CA_BUNDLE`, timeout/retry/presign settings, SSE/KMS settings, `SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED`, `SECUREDRIVE_DOWNLOAD_URL_SECONDS`.

Production cần HTTPS, TLS verification, rotation, network restrictions, encryption/backup policy đã nghiệm thu. Không tắt bảo vệ để đưa dev Compose lên production.

## Baseline và kiểm thử

Các lệnh Python bên dưới dùng Python portable + `-X utf8`. Check/test dev đặt `DEBUG=true` và direct-download false trong process; không sửa `.env`. Baseline nguyên môi trường thất bại do process env override chế độ dev làm HTTP endpoint bị reject; với dev override, check/migration đạt. Lệnh `manage.py test` không label từ repo root từng trả **0 test**; không tính là PASS. Chạy full suite bằng label từ backend và sau đó runner DB cách ly.

| Lệnh / kiểm tra | Trạng thái | Bằng chứng / giới hạn |
| --- | --- | --- |
| Django `check` với dev process config | PASS | `final-django-check.log`: no issues. |
| `makemigrations --check --dry-run` | PASS | `final-migrations.log`: no changes detected; không thêm migration. |
| Full regression đầu tiên | FAIL, đã sửa contract test | 567 bài, 1 fail về public signer theo kỳ vọng cũ, 16 skip; `initial-backend-regression.log`. Không coi là baseline trước mọi sửa đổi. |
| Adapter regression cuối | PASS | 33 bài; `final-adapter-tests.log`. Mock/unit chỉ chứng minh logic adapter, không chứng minh SeaweedFS. |
| Targeted với test DB cũ `--keepdb` | FAIL môi trường test state | 5 error do baseline Storage Plan bị flush; chuyển sang DB test mới, không sửa dữ liệu app. |
| Full regression DB riêng | PASS với 19 skip | 571 bài: 552 pass, 19 skip, 0 lỗi, 668,595 giây; `final-backend-regression.log`. Suite được load trước thay đổi ZIP cuối; toàn bộ 61 bài sharing đã chạy lại sau sửa ZIP. Các bài runtime SeaweedFS/MinIO skip không tính là tương thích PASS. |
| ZIP mixed S3/AES + integrity/RBAC | PASS | 2 bài; `shared-zip-regression.log`. S3 được mock trong bài này; AES và ZIP đọc thật. |
| Sharing regression sau sửa ZIP | PASS | 61 bài, 0 fail; `final-sharing-regression.log`. |
| `npm run lint` | PASS | `baseline-frontend-lint.log`. |
| `npx tsc --noEmit` | PASS | `baseline-frontend-typecheck.log`. |
| Node test toàn bộ `*.test.mts` | PASS | 159 pass, 0 fail; `baseline-frontend-tests.log`. |
| `npm run build` sandbox | FAIL baseline network | Không tải được Poppins từ Google Fonts; `baseline-frontend-build.log`. |
| `npm run build` có quyền mạng | PASS | `baseline-frontend-build-network.log`. |
| Config generator unit/self-check | PASS | 2 bài; `configure-tests.log`. Cấu hình local cũng đã sinh thành công. |
| YAML parse/static topology | PASS | `compose-static-check.txt`; không thay cho `docker compose config`. |
| Python compile / Node syntax / scoped `git diff --check` | PASS | Chỉ static; Git có warning CRLF theo convention máy. |
| `docker compose config/up/ps/logs` | BLOCKED | Không có Docker usable; chưa có container/runtime evidence. |
| SeaweedFS Windows `weed version` | BLOCKED | Application Control chặn binary đã tải/verify digest. |
| `smoke.py test` | BLOCKED | Không có server ở local S3 endpoint; setUpClass lỗi, 0 test thực thi. `real-storage-gate.log`. |
| PostgreSQL Filer metadata / persistence restart | BLOCKED | Chưa provision Filer DB hoặc chạy cluster; script/probe đã có. |
| Chrome CORS / hostname / exposed headers | NOT RUN / BLOCKED | Script browser gate đã có, cần SeaweedFS chạy thật. |
| Worker thật trên SeaweedFS | NOT RUN / BLOCKED | Opt-in tests đã có; skip không được tính PASS. |
| Full UI My Drive/Workspace regression với SeaweedFS | NOT RUN / BLOCKED | Không đổi UI; backend/unit hiện có không thay được end-to-end. |

## Acceptance gate

**Chưa có gate runtime SeaweedFS nào được đánh PASS.** Code/static/unit pass không chứng nhận tương thích. Cần chạy và lưu bằng chứng cho:

1. Compose/CLI đúng image, master nhìn thấy volume; Filer ghi/đọc PostgreSQL metadata riêng.
2. Credential/anonymous deny, app không được quản trị bucket, admin API không public.
3. Multipart, presigned URL, ListParts/resume, Abort, Range, metadata/copy/versioning và conditional copy thật.
4. Part checksum đúng/sai/thiếu/sai signed header, Complete/Head checksum semantics; không bỏ assertion nếu thiếu hỗ trợ.
5. Chrome từ Windows dùng đúng signed host, CORS và ETag/checksum đọc được.
6. Restart toàn cluster giữ bucket/object/version/Filer metadata.
7. Worker hiện tại hoàn tất upload và quota; My Drive/Workspace permissions/isolation/audit và tất cả thao tác người dùng qua endpoint mới.

## MinIO removal, reset và Task 02

**Chưa thực hiện:** backup PostgreSQL/config cho cutover, provision metadata DB, đổi endpoint backend, reset 31 file, chỉnh quota/share/history, dừng/gỡ MinIO container/service/volume hoặc apply SQL bootstrap. Lý do: runtime SeaweedFS chưa thể kiểm thử và dữ liệu chưa được xác minh disposable. Không coi câu xác nhận trong tài liệu đính kèm là bằng chứng kiểm kê từng file.

Đã chuẩn bị dry-run chỉ đọc và quy trình scoped reset trong runbook. Chỉ xây/áp dụng exact-ID deletion manifest khi xác minh môi trường/file thử nghiệm, backup và restore test đạt. Bảo toàn Users, Organizations/Tenants, Workspaces và audit lịch sử; quota/sharing/FK phải đối chiếu các file còn giữ. Không có command `flush` hoặc xóa volume tự động.

Trước Task 02: toàn bộ gate trên phải đạt, cutover/reset được xác minh và hoàn thành, không còn runtime MinIO trong cấu hình đang dùng, xác định rõ kế hoạch integrity/claims/quota/idempotency thay cho worker. Chưa gỡ worker hoặc thay thuật toán AES trong Task 01.

Quy trình audit → baseline → adapter/config → gate thật → cutover là mẫu có thể đóng gói thành Agent Skill sau khi runtime gate được nghiệm thu.
