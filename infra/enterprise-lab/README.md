# Enterprise SeaweedFS Simulator — 1 laptop / 2 isolated clusters

> Đối chiếu P0 16/11/2026: [ADR-0010](../../docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) giữ storage Platform/Enterprise và PostgreSQL Filer độc lập, cùng application codebase với Tenant/Binding riêng. [P0 baseline](../../docs/REFACTOR_P0_BASELINE_2026-11-16.md) chưa nghiệm thu runtime Enterprise; source Compose hoặc container healthy không chứng nhận Enterprise My Drive/CSE/recovery. Các lệnh provisioning dưới đây chỉ chạy khi có phạm vi vận hành được duyệt, không thuộc P0.

Mục đích: tạo một **SeaweedFS Cluster doanh nghiệp mô phỏng** trên cùng máy Windows với
BlueDrive Platform, **không chuyển endpoint, không thay SeaweedFS Platform hiện có**.
Cluster này dùng Compose project `bluedrive-enterprise-lab`, các Docker volume và
network riêng, S3 ở loopback port `8433`, PostgreSQL Filer riêng trong Docker.

> Đây là môi trường development/LAN một máy. Không có HA, không bật TLS và không
> được đưa ra Internet. `Platform` tiếp tục giữ PostgreSQL nghiệp vụ và storage
> hiện có. Không coi container `healthy` là Storage Ready trước khi chạy gate thật.

## 1. Tạo cấu hình lần đầu (không ghi đè)

Từ thư mục gốc dự án, trên PowerShell:

```powershell
$Python = (Resolve-Path .\.venv\Scripts\python.exe).Path
& $Python -X utf8 .\infra\enterprise-lab\configure.py
$Compose = (Resolve-Path .\infra\enterprise-lab\compose.yml).Path
$StorageEnv = Join-Path (Split-Path $Compose) '.env'
docker compose --env-file $StorageEnv -f $Compose config --quiet
```

Generator dùng lại `infra/seaweedfs/configure.py` để tạo `.env`, `.local/filer.toml`,
`.local/bootstrap.sql`, `.local/s3.json`, `.local/cors.json` và `.local/backend.env`.
Tất cả secret được sinh độc lập với cluster Platform. Các file này không được upload,
commit hoặc in lên terminal; thư mục `.local` bị Git ignore.

**Nếu `.local` đã tồn tại, không chạy lại generator**, đặc biệt khi có data trong
`postgres_data` và `volume_data`. Không xóa Docker volume để xử lý lỗi kết nối.

## 2. Chạy cluster doanh nghiệp

```powershell
docker compose --env-file $StorageEnv -f $Compose up -d --wait --wait-timeout 180
docker compose --env-file $StorageEnv -f $Compose ps
```

Không có cổng PostgreSQL, Master, Filer hoặc Volume Server mở ra host.
S3 chỉ mở trên `127.0.0.1:8433`; phiên bản Platform dùng `127.0.0.1:8333` trong
runbook cũ. Docker networks khác nhau, container service names giống nhau nhưng
không xung đột do khác Compose project.

PostgreSQL tự tạo role/database/table Filer **chỉ trong lần khởi tạo volume trống**
qua file `.local/bootstrap.sql`. Nếu database đã tồn tại, script init không chạy
lại; không xóa volume và không tự thay credential.

## 3. Kiểm tra thật, KHÔNG tự cutover

Chỉ bật cờ test sau khi xác minh đúng endpoint/bucket của cluster doanh nghiệp.
Lệnh bên dưới dùng harness chung, không tạo thêm bộ kiểm thử S3 thứ hai:

```powershell
$env:SEAWEEDFS_ALLOW_TEST_WRITES = '1'
& $Python -X utf8 .\infra\seaweedfs\smoke.py init-bucket --config-dir .\infra\enterprise-lab
& $Python -X utf8 .\infra\seaweedfs\smoke.py test --config-dir .\infra\enterprise-lab
& $Python -X utf8 .\infra\seaweedfs\smoke.py browser --config-dir .\infra\enterprise-lab
Remove-Item Env:SEAWEEDFS_ALLOW_TEST_WRITES
```

Các bước cần xác minh: S3 signed requests, bucket versioning/CORS, multipart,
checksum, browser presigned URL, metadata `seaweedfs_enterprise_meta.public.filemeta`
và persistence sau restart. `smoke.py test` có thể báo BLOCKED nếu provider không
đáp ứng contract; không bỏ assertions để lấy kết quả xanh. Không bật multi-cluster
routing cho tới khi hoàn tất storage gate và xác minh target của các file hiện có.

### Dừng mà không mất dữ liệu

```powershell
docker compose --env-file $StorageEnv -f $Compose stop
```

Không dùng `down -v`. Không xóa `.local`, `.env`, `postgres_data` hoặc `volume_data`.

## 4. Sau khi có laptop thứ hai

Di chuyển **cả Enterprise Compose project lẫn dữ liệu PostgreSQL/Filer/Volume và
secret liên quan** sang laptop doanh nghiệp; không đụng vào SeaweedFS Platform.
Phải backup/restore và kiểm tra object trước khi đổi endpoint, tránh thay hostname
sau khi ký presigned URL. Production/LAN hai máy cần thiết kế HTTPS, firewall,
DNS/route và quyền truy cập từ browser/worker phù hợp. Không chuyển bằng cách chỉ
copy file Compose hoặc đổi S3 host trong metadata đang dùng.
