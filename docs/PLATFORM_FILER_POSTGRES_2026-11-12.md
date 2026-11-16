# Platform SeaweedFS — PostgreSQL Filer Docker

Ngày kiểm tra: **12/11/2026**, Asia/Bangkok. Phạm vi: bootstrap PostgreSQL riêng, khởi động Platform Filer/S3, probe S3 không xóa và persistence. **Đã triển khai và đạt các gate trong phạm vi này; chưa cutover MinIO hoặc nghiệm thu toàn bộ Task 01.**

## Cấu hình đã triển khai

| Hạng mục | Kết quả thực tế |
| --- | --- |
| Compose project | `bluedrive-seaweedfs` |
| PostgreSQL image/server | `postgres:17-alpine` / PostgreSQL **17.11** |
| PostgreSQL data | Named volume `bluedrive-seaweedfs_postgres_data`, mount `/var/lib/postgresql/data` |
| Network | `bluedrive-seaweedfs_storage`; không join network Enterprise |
| Host DB port | Không có port binding |
| Filer metadata | `postgres:5432`, DB `seaweedfs_meta`, user `seaweedfs_filer` |
| Quyền Filer | NOSUPERUSER, NOCREATEDB, NOCREATEROLE; không dùng tài khoản bootstrap |
| Backend metadata | Chỉ `[postgres]` enabled; `[leveldb2]` disabled; `createTable=false` |
| Schema | `public.filemeta`, owner `seaweedfs_filer`; `dirhash bigint`, `name/directory varchar`, `meta bytea`; PK `(dirhash, name)` |
| Dependency | Filer chờ PostgreSQL và Volume healthy; S3 chờ Filer healthy |
| S3 Platform | `filer:8888`, publish `127.0.0.1:8333` |
| Enterprise S3 | Giữ `127.0.0.1:8433`; container không restart |

Docker tự bootstrap role/database/table qua `.local/bootstrap.sql`; không tạo role trên Windows. Mật khẩu quản trị PostgreSQL mới được sinh bằng bộ sinh ngẫu nhiên bảo mật, độc lập mật khẩu Filer. Credential Filer và hai identity S3 cũ được giữ nguyên; thêm một identity giới hạn riêng bucket probe. Không ghi credential vào source hoặc báo cáo.

## Kết quả kiểm tra lần này

| Gate / lệnh | Số kiểm tra | Trạng thái và bằng chứng |
| --- | --- | --- |
| `docker compose --env-file infra/seaweedfs/.env -f infra/seaweedfs/compose.yml config --quiet` | 1 config | **PASS**; kiểm tra thêm JSON rendered cho dependency/port/đích Filer |
| `python -X utf8 -m unittest discover -s infra/seaweedfs -p test_configure.py -v` | 3 tests | **PASS**, 0 fail/skip; bao gồm từ chối host/port sai, password quản trị trùng Filer và ghi đè local |
| `python -X utf8 -m unittest discover -s infra/enterprise-lab -p test_configure.py -v` | 2 tests | **PASS**, 0 fail/skip; generator dùng chung vẫn tương thích Enterprise |
| `docker exec ... psql -U postgres -d seaweedfs_meta ...` | Schema/role/PK | **PASS**; bảng và quyền đúng; đăng nhập TCP bằng password role Filer thành công |
| `docker compose ... up -d --no-deps --wait postgres`, rồi `... up -d --no-deps --wait filer s3` | 5 service | **PASS**; PostgreSQL/Master/Volume/Filer/S3 healthy |
| Probe Python/boto3 qua stdin, cấu hình từ private local | 12 kiểm tra chức năng | **PASS**; chi tiết bên dưới |
| `docker compose ... restart postgres master volume filer s3`, rồi `... up -d --no-recreate --wait --wait-timeout 180 postgres master volume filer s3` | 5 container | **PASS**; restart đúng Platform, không recreate, ID/mount giữ nguyên |
| Đọc lại probe, kiểm tra metadata/config/isolation qua Python/boto3/Docker | 10 kiểm tra persistence/cách ly | **PASS**; 2 object khớp size/SHA-256; 5 hàng metadata bucket và digest không đổi; port/volume/network đúng |
| Repository safety guard, `git diff --check` và kiểm tra whitespace/link cho file untracked sửa trong nhiệm vụ | Source | **PASS**; không phát hiện secret trong source; file private được ignore |
| Full provider contract, DELETE/abort, browser CORS, Django finalizer, full backend/frontend regression | Không chạy | **SKIP**; ngoài phạm vi bootstrap hoặc có xóa fixture; không coi probe này là chứng nhận Task 01/cutover |

Các lệnh Python đã dùng `.venv/Scripts/python.exe` **3.12.10**; Docker Engine **29.8.2**, Compose **5.6.0**. Trong sandbox cũ Docker/Python per-user và private ACL không truy cập được; đã thực thi bằng quyền tài khoản hiện tại qua escalation được duyệt, không mở rộng ACL.

12 kiểm tra probe gồm: tạo bucket riêng bằng operator; PUT kèm SHA-256 request checksum; HEAD size/metadata; GET đối chiếu SHA-256 toàn file; Range; LIST; anonymous deny; sai secret deny; identity test bị từ chối ngoài bucket; presigned GET; multipart UploadPart/ListParts/Complete và SHA-256 toàn file; số hàng `filemeta` tăng sau ghi. Request dữ liệu dùng identity giới hạn bucket. Không dùng ETag làm checksum toàn file.

Lần chạy probe đầu dừng trước mọi S3 write do assertion giả định `filemeta` rỗng. Filer đã tạo 10 hàng hệ thống khi khởi động; sửa phép kiểm tra thành số hàng trước/sau. Lần chạy đầy đủ đạt 12/12, metadata tăng **10 → 17**. Kiểm tra persistence so sánh riêng 5 hàng bucket probe để tách metadata hệ thống có thể tiếp tục phát sinh.

## Probe và bằng chứng được giữ lại

Bucket: `platform-filer-pg-20261112-eae93e2d`.

| Object | Size | SHA-256 |
| --- | ---: | --- |
| `postgres-probe/single.bin` | 98.304 byte | `6f38f690ee51de08828ef5b24a0b2f05eaf684d1783ca8ec5fab887a99b29a64` |
| `postgres-probe/multipart.bin` | 5.272.576 byte | `be2549cd95529f4e657d702c862dde21bb70ccb1aafe74882bd31dd6494f4e01` |

Không phát DELETE, abort multipart hoặc xóa bucket/volume. Hai object, bucket, identity test và manifest được giữ lại theo yêu cầu không tự động xóa. Không cần chạy lại `init-bucket` trên bucket này.

File private trong `infra/seaweedfs/.local/`:

- `platform-postgres-test.env`: credential identity bucket test.
- `platform-postgres-probe.json`: key, size, SHA-256, metadata digest và snapshot container trước restart.
- `platform-postgres-manifest.json`: hash cấu hình bảo vệ và snapshot container ban đầu.
- `platform-postgres-result.json`: kết quả đã lọc, trạng thái container và digest image.
- `before-platform-postgres-20261112/`: backup `.env`, `filer.toml`, `s3.json`, `bootstrap.sql` trước thay đổi; giữ private, không upload/commit.

Image digest thực tế:

- PostgreSQL: `sha256:e5d2edd28b1f8d40a0a6c0c9cdc545b19b56a0d5d88f94bc11a97d970d4700d0`.
- SeaweedFS: `sha256:ccad23e18639c8b98cee17e7100b95830a06077b56d8e5b006d6dcf8ec5e94a0`.

## Bảo toàn phạm vi và file đã thay đổi

Container Enterprise và MinIO giữ nguyên ID, mount, thời điểm khởi động. Master/Volume Platform giữ nguyên ID/mount, chỉ restart để test persistence. Hash `backend/.env`, `.env` và các file private Enterprise, cùng bootstrap/backend.env/CORS Platform không đổi. Không chạy lệnh ghi DB Django, không sửa Storage Connection, không di chuyển MinIO, không chạy `down -v`, không commit/push.

Source/config/tài liệu đã sửa trong nhiệm vụ:

1. `infra/seaweedfs/compose.yml`: PostgreSQL/volume/health dependency; bỏ host gateway của Filer.
2. `infra/seaweedfs/.env.example`: host `postgres`, thêm biến mật khẩu bootstrap rỗng.
3. `infra/seaweedfs/configure.py`: giữ generator chung, kiểm tra đích DB container và mật khẩu bootstrap tách biệt.
4. `infra/seaweedfs/test_configure.py`: assertions PostgreSQL/container/secret/SQL và test từ chối password trùng.
5. `infra/seaweedfs/README.md`: runbook Docker thay bootstrap Windows, giới hạn test có xóa fixture.
6. `MAP.md`: bản đồ service và bằng chứng mới.
7. `docs/BLUEDRIVE_BAN_GIAO_TASK01.md`: chú thích trạng thái lịch sử.
8. `docs/BLUEDRIVE_SEAWEEDFS_RUNTIME.md`: chuyển liên kết hiện hành sang báo cáo mới.
9. `docs/ADR-0007-platform-filer-postgres-container.md`: quyết định và rollback giữ dữ liệu.
10. Báo cáo này.

Private local sửa `.env` (host và thêm secret bootstrap), `.local/filer.toml` (hostname), `.local/s3.json` (thêm identity test); tạo các file bằng chứng/backup liệt kê ở trên. Không chạy lại generator trên local hiện hữu.

Giống chạy thử sổ kho mới: đã kiểm tra ghi, đọc và giữ nguyên sau tắt/bật; chưa chuyển địa chỉ kho của ứng dụng. Rủi ro còn lại là môi trường một máy, tag PostgreSQL chưa ghim digest và backup/restore DB mới chưa được nghiệm thu. Quy trình bootstrap → probe không xóa → restart → đối chiếu manifest có thể bổ sung vào skill `bluedrive-storage-validation` khi cần tái sử dụng.
