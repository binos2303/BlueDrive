# Bàn giao BlueDrive — tiếp tục SeaweedFS Task 01

**Cập nhật 12/11/2026:** Platform Filer dùng PostgreSQL Docker độc lập theo yêu cầu mới; xem [báo cáo triển khai](PLATFORM_FILER_POSTGRES_2026-11-12.md) và [runbook hiện hành](../infra/seaweedfs/README.md). Các bước pgAdmin/Windows bên dưới là lịch sử ngày 10/11, không còn bắt buộc cho Platform Compose. Chưa cutover; không áp dụng quyền xóa/chuyển dữ liệu từ bản bàn giao cũ cho nhiệm vụ mới.

Ngày cập nhật: **10/11/2026**, múi giờ Asia/Bangkok.

**Dừng tại bước kết nối và khởi tạo PostgreSQL metadata thủ công. Chưa cutover, chưa xóa dữ liệu test, chưa ngừng MinIO.** Đây là bản tổng hợp để người dùng làm phần thao tác máy tính rồi quay lại; các trạng thái dưới đây là kết quả lần kiểm tra gần nhất, không phải kiểm tra lại khi mở tài liệu.

## 1. Phạm vi và yêu cầu đã thống nhất

1. Có Docker Desktop và Python 3.12 hoạt động trên Windows.
2. Dựng SeaweedFS bằng Compose: Master, Volume, Filer và S3; metadata PostgreSQL dùng database/role riêng.
3. Kiểm thử thật S3, multipart, SHA-256, presigned URL, CORS, resume, finalizer và lưu dữ liệu sau restart.
4. Khi các gate đạt, backup rồi chuyển BlueDrive sang SeaweedFS; kiểm tra lại trước khi ngừng MinIO.

Người dùng sẽ tự điều hướng Windows, Docker Desktop, pgAdmin và nhập thông tin kết nối. Trợ lý phụ trách code/config, đọc kết quả và hướng dẫn. **Không tiếp tục tự động điều khiển giao diện.**

Người dùng đã xác nhận các file đang bàn là dữ liệu thử nghiệm và cho phép bỏ. Việc này áp dụng cho dữ liệu file thử nghiệm trong BlueDrive/MinIO, không phải xóa source code, tài khoản, tenant, workspace hoặc toàn bộ database. Chưa thực hiện xóa; khi tiếp tục vẫn phải kiểm kê đúng phạm vi, backup và đạt gate trước khi reset/cutover. Không cần yêu cầu lại xác nhận dữ liệu test đã được cấp trong phiên này.

Không thực hiện Task 02/03; giữ finalizer, kiểm quyền, quota, audit và cơ chế đọc AES legacy.

Giống như chuyển sang kho mới: đường vào và điện đã hoạt động, nhưng cần cấp chìa khóa riêng cho sổ kho, chạy thử rồi mới chuyển địa chỉ giao hàng.

## 2. Kết quả môi trường và runtime đã xác minh

| Hạng mục | Kết quả gần nhất |
| --- | --- |
| Python | 3.12.10; `.venv\Scripts\python.exe` chạy được, `pip check` đạt. Không cần tạo lại virtualenv. |
| Docker Desktop | 4.95.0; Engine 29.8.2; Compose 5.6.0; Linux engine qua WSL 2 hoạt động. |
| Docker CLI | `C:\Users\dang2\AppData\Local\Programs\DockerDesktop\resources\bin\docker.exe`; User PATH đã có, tiến trình terminal cũ có thể chưa cập nhật. |
| PostgreSQL | Server 18.6 trên Windows, port 5432; Docker network đã kết nối TCP được tới host. TCP thành công chưa chứng minh đăng nhập Filer thành công. |
| Image SeaweedFS | `chrislusf/seaweedfs:4.53`; `weed version` chạy được trong Docker. |
| Image digest đã tải | `sha256:ccad23e18639c8b98cee17e7100b95830a06077b56d8e5b006d6dcf8ec5e94a0` |
| Compose | `config --quiet` đạt; có network riêng và persistent volumes. |
| Master / Volume | Đã chạy healthy; Master thấy Volume, capacity 32. |
| Filer / S3 | Chưa khởi động; đang chờ metadata database riêng. |
| Role/database metadata | Lần kiểm tra cuối chưa có `seaweedfs_filer` / `seaweedfs_meta`; chưa nhận được xác nhận người dùng tạo xong. |
| pgAdmin admin | Đã kiểm tra phiên đăng nhập lưu sẵn có superuser/CREATEDB/CREATEROLE; không trích xuất mật khẩu. |
| Role ứng dụng | Có CREATEDB nhưng không có CREATEROLE/superuser, nên không dùng để tạo role Filer. |
| MinIO | Container `securedrive-minio` vẫn chạy, image `quay.io/minio/aistor/minio:latest`, host loopback port 9000–9001. |
| Dữ liệu nguồn | Đã đọc và đối chiếu 31/31 object khớp SHA-256, tổng 5.693.666 byte; không có upload đang hoạt động tại lần kiểm tra. |

Chỉ S3 đích publish lên host `127.0.0.1:8333`. Các cổng quản trị Master/Volume/Filer không publish. Endpoint Windows backend dự kiến `http://127.0.0.1:8333`; public signer `http://s3.localhost:8333`; bucket dự kiến `bluedrive-dev`. Các địa chỉ này **chưa áp dụng để cutover backend**.

## 3. Code và cấu hình đã chuẩn bị

Thư mục dự án: `C:\Users\dang2\Project\SecureDrive`.

| Nhóm | File / thay đổi |
| --- | --- |
| Hạ tầng | `infra/seaweedfs/compose.yml`: bốn dịch vụ, volumes, network, healthcheck, image 4.53. |
| Cấu hình | `.env.example`, `configure.py`, `test_configure.py`: sinh cấu hình private, tách operator/app S3, CORS origin cụ thể và metadata DB riêng; từ chối ghi đè `.local` có sẵn. |
| Gate thật | `smoke.py`, `browser-smoke.mjs`: S3, Chrome CORS, kiểm tra persistence sau restart. |
| Test DB cách ly | `regression.py`: tạo test database tên ngẫu nhiên mới; tránh `--keepdb` với dữ liệu seed đã bị flush ở suite cũ. |
| Audit | `backend/files/management/commands/audit_storage_cutover.py` và test: kiểm kê chỉ đọc, chưa có lệnh reset/xóa. |
| Integration | `backend/files/tests/test_seaweedfs_integration.py`, `test_seaweedfs_finalizer_integration.py`: S3 thật và upload API → worker → download/quota; gồm checksum sai và file rỗng. |
| Public signer | `backend/files/storage_adapters/factory.py`, `backend/securedrive/settings.py`, `backend/.env.example`: upload dùng public endpoint khi được cấu hình, độc lập với cờ direct download. Không đổi host sau khi ký. |
| Provider mặc định | `backend/files/finalization.py`: config mới dùng provider chung `s3`; giữ finalizer hiện tại. |
| Shared ZIP | `backend/sharing/views.py`, `test_archive_storage.py`: đọc qua reader/guard dùng chung để hỗ trợ S3 và AES legacy, giữ kiểm quyền/hash/version. |
| Regression liên quan | Bổ sung/cập nhật test public signer, provider mặc định, audit không đổi dữ liệu, shared ZIP. |
| Tài liệu | Runbook `infra/seaweedfs/README.md`, báo cáo lịch sử và evidence trong `docs/`. Có cập nhật ghi chú MinIO cũ trong tài liệu/cấu hình liên quan. |

Đã sinh local: `infra/seaweedfs/.env` và `.local/filer.toml`, `s3.json`, `cors.json`, `bootstrap.sql`, `bootstrap-role.sql`, `backend.env`. Các file chứa secret được Git ignore và có ACL riêng. **Giữ nguyên, không chạy lại `configure.py`, không gửi nội dung vào chat hoặc commit Git.**

Chưa merge `.local/backend.env` vào `backend/.env`, chưa đổi DB ứng dụng, chưa đổi AES, chưa xóa file/object/volume và chưa commit các thay đổi. Repository có nhiều thay đổi từ trước thuộc các phần khác; không được reset hoặc coi mọi file dirty là của Task 01.

## 4. Những kiểm tra đã đạt và giới hạn

| Kiểm tra | Kết quả đã lưu |
| --- | --- |
| Django check và kiểm tra migration | Đạt với cấu hình dev trong process; không thêm migration cho Task 01. |
| Backend regression DB riêng | 571 bài: 552 pass, 19 skip, không lỗi. Suite này được load trước sửa ZIP cuối; sau đó đã chạy lại toàn bộ sharing. |
| Sharing sau sửa ZIP | 61 bài đạt; gồm 2 regression ZIP S3/AES. S3 trong bài ZIP được mock. |
| Adapter regression | 33 bài đạt. |
| Config generator | 2 bài đạt. |
| Frontend | 159 Node tests, lint, TypeScript đạt; build có mạng đạt. Build sandbox từng lỗi tải Google Fonts. |
| Python/Docker/Compose/Master/Volume | Đạt như bảng runtime bên trên. |
| S3 / multipart / SHA-256 / presigned / resume thật | **Chưa đạt gate thực tế**; lần thử trước không có server, không bài nào chạy thành công. |
| Browser CORS / finalizer trên SeaweedFS / restart persistence | **Chưa chạy**. |
| Backup và kiểm tra restore / reset test data / cutover / dừng MinIO | **Chưa thực hiện**. |

Unit test pass, test bị skip hoặc container healthy không thay thế được kiểm thử tính tương thích SeaweedFS thực tế. Nếu checksum hay contract không hỗ trợ phải phân tích lỗi; không bỏ assertion để ép pass.

## 5. Bạn làm thủ công trong pgAdmin

Mục tiêu phần này: tạo đúng database riêng và bảng `public.filemeta`, rồi kiểm tra đăng nhập bằng role Filer. Chưa chạy smoke test, chưa sửa endpoint BlueDrive.

### Bước A — kiểm tra trước khi tạo

Mở pgAdmin, kết nối server PostgreSQL 18 bằng phiên admin đã lưu. Mở **Query Tool trên database `postgres`** và chạy:

```sql
SELECT EXISTS (
    SELECT 1 FROM pg_roles WHERE rolname = 'seaweedfs_filer'
) AS filer_role_exists;

SELECT EXISTS (
    SELECT 1 FROM pg_database WHERE datname = 'seaweedfs_meta'
) AS metadata_database_exists;
```

Nếu cả hai `false`, làm tiếp. Nếu có `true`, không chạy lại câu CREATE tương ứng và không drop/recreate; báo lại trạng thái để kiểm tra phần đã tạo.

### Bước B — tạo role bằng file có sẵn

Trong Query Tool admin, dùng **Open File / Ctrl+O** mở:

```text
C:\Users\dang2\Project\SecureDrive\infra\seaweedfs\.local\bootstrap-role.sql
```

Chạy F5. Kết quả mong đợi: `CREATE ROLE`.

File này chứa mật khẩu đã sinh khớp cấu hình Filer; mở trực tiếp tại máy. Không cần gõ lại mật khẩu và không gửi nội dung file/ảnh chụp phần mật khẩu.

**Không mở rồi F5 toàn bộ `bootstrap.sql` trong Query Tool**: file đó dành cho `psql`, có lệnh `\set` và `\connect` mà Query Tool không xử lý như SQL.

### Bước C — tạo database riêng

Mở tab Query Tool admin trên `postgres`, bật **Auto-commit**, không dùng `BEGIN`. Chạy **riêng câu này**:

```sql
CREATE DATABASE seaweedfs_meta OWNER seaweedfs_filer;
```

Mong đợi `CREATE DATABASE`. Sau khi thành công, chạy riêng:

```sql
REVOKE ALL ON DATABASE seaweedfs_meta FROM PUBLIC;
```

### Bước D — tạo schema/table trong đúng database mới

Refresh danh sách Databases. Chọn **`seaweedfs_meta` → Query Tool** bằng admin. Kiểm tra trước:

```sql
SELECT current_database(), current_user;
```

Chỉ tiếp tục khi `current_database()` đúng `seaweedfs_meta`. Chạy:

```sql
REVOKE ALL ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO seaweedfs_filer;
SET ROLE seaweedfs_filer;

CREATE TABLE public.filemeta (
    dirhash BIGINT,
    name VARCHAR(65535),
    directory VARCHAR(65535),
    meta BYTEA,
    PRIMARY KEY (dirhash, name)
);

RESET ROLE;
```

Nếu báo table đã tồn tại, dừng và báo lại, không xóa bảng. Filer được cấu hình `createTable=false`, nên phải có bảng trước khi chạy.

### Bước E — kiểm tra kết quả và kết nối bằng role Filer

Trong Query Tool admin trên `seaweedfs_meta`:

```sql
SELECT datname, pg_get_userbyid(datdba) AS owner
FROM pg_database WHERE datname = 'seaweedfs_meta';

SELECT rolname, rolsuper, rolcreatedb, rolcreaterole
FROM pg_roles WHERE rolname = 'seaweedfs_filer';

SELECT schemaname, tablename, tableowner
FROM pg_tables
WHERE schemaname = 'public' AND tablename = 'filemeta';
```

Mong đợi DB owner và table owner đều `seaweedfs_filer`; ba quyền superuser/createdb/createrole đều `false`.

Đăng ký thêm một connection trong pgAdmin để kiểm tra đăng nhập Filer thực sự, giữ nguyên connection admin:

| Trường | Giá trị |
| --- | --- |
| Name | `SeaweedFS metadata local` |
| Host name/address | `127.0.0.1` |
| Port | `5432` |
| Maintenance database | `seaweedfs_meta` |
| Username | `seaweedfs_filer` |
| Password | Lấy giá trị `FILER_DB_PASSWORD` trong `infra/seaweedfs/.env` tại máy; không gửi lên chat. |
| SSL mode | `disable` theo cấu hình development hiện tại; không áp dụng cho production. |

Trong Query Tool của connection Filer, chạy:

```sql
SELECT current_database(), current_user;
SELECT count(*) AS metadata_rows FROM public.filemeta;
```

Mong đợi database/user đúng như trên và đọc bảng không lỗi; bảng mới thường có 0 dòng. Đây là kiểm tra đăng nhập local. Container Filer dùng `host.docker.internal:5432`; xác minh đường đăng nhập từ Docker sẽ làm ở lượt tiếp theo.

Nếu lỗi, chỉ gửi lại bước đang làm, nội dung lỗi đã che thông tin nhạy cảm và trạng thái role/database/table. Không sửa firewall/`pg_hba.conf`, không mở quyền rộng hoặc đổi mật khẩu ngẫu nhiên để thử.

## 6. Khi quay lại, gửi thông tin này

```text
Tiếp tục BlueDrive Task 01 theo docs/BLUEDRIVE_BAN_GIAO_TASK01.md.
Tôi đã làm đến bước: ...
Role seaweedfs_filer: đã có / chưa có.
Database seaweedfs_meta: đã có / chưa có.
Table public.filemeta: đã có / chưa có.
Đăng nhập role Filer và SELECT count(*): thành công / lỗi ...
Docker Desktop: đang chạy / chưa chạy.
Tôi tự thao tác giao diện; bạn phụ trách code và hướng dẫn.
```

Không cần gửi password, `.env`, file bootstrap hoặc presigned URL.

## 7. Thứ tự tiếp tục dành cho trợ lý

1. Đọc tài liệu này và kiểm tra trạng thái hiện tại, không mặc định kết quả runtime cũ vẫn còn đúng. Không lặp lại cài Docker/Python nếu vẫn dùng được.
2. Xác minh owner/schema và đăng nhập metadata từ Docker; khởi động Filer/S3; xác minh đủ bốn dịch vụ. Không tạo lại secret hiện có.
3. Khởi tạo bucket bằng operator một lần; chạy storage smoke, Chrome CORS, integration finalizer trên test DB riêng và persistence qua restart. Lưu bằng chứng đã loại secret. Lệnh chi tiết có trong runbook.
4. Nếu gate lỗi, sửa/đánh giá tương thích rồi test lại phần liên quan; chưa cutover khi chưa đạt. Giữ SHA-256 toàn file, version pinning, quyền và quota.
5. Sau các gate đạt, backup DB ứng dụng và cấu hình ở nơi private, kiểm tra restore cách ly. Kiểm kê lại danh sách file test; chuẩn bị reset theo exact IDs với FK/quota/sharing nhất quán, giữ Users/Tenants/Organizations/Workspaces và audit. Người dùng đã cho phép bỏ file test; chưa có code reset được áp dụng.
6. Áp dụng riêng biến storage trong `.local/backend.env`, giữ DB ứng dụng/AES và worker. Kiểm tra các luồng BlueDrive thực tế với SeaweedFS.
7. Chỉ sau đó ngừng đúng container `securedrive-minio`; không nhầm cấu hình MinIO community cũ với image AIStor runtime. Không xóa volume bằng `down -v`.

Sau khi hoàn tất và nghiệm thu, có thể đóng gói quy trình kiểm tra → gate → backup → cutover thành một Agent Skill dùng lại. Hiện chưa tạo skill.

## 8. Tài liệu, evidence và giới hạn truy cập

- [Runbook lệnh triển khai và kiểm thử](../infra/seaweedfs/README.md).
- [Báo cáo source/test lượt đầu](BLUEDRIVE_SEAWEEDFS_TASK01.md): giữ như lịch sử; các ghi chú chưa có Docker/Python và chưa được phép bỏ dữ liệu đã được cập nhật bởi bản bàn giao này.
- [Báo cáo runtime lượt sau](BLUEDRIVE_SEAWEEDFS_RUNTIME.md).
- Evidence source/test cũ: `docs/task01-evidence/`.
- Evidence Python, image, Master/Volume và SHA-256 nguồn: `docs/task01-runtime-evidence/`.

Sandbox không đọc được một số file private theo ACL hiện có. Automatic approval review từng **từ chối** đề xuất cấp sandbox quyền đọc file SQL chứa credential vì mở rộng quyền bí mật không cần thiết. Quyền đó chưa được áp dụng. Phương án tiếp tục là người dùng chạy bootstrap qua pgAdmin bằng tài khoản đã có, không trích xuất mật khẩu admin hoặc mở rộng ACL.

Lượt bàn giao này chỉ tổng hợp tài liệu; không chạy lại runtime tests, không điều khiển GUI và không thay đổi dịch vụ hay dữ liệu.
