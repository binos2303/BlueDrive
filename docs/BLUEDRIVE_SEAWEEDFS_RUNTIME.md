# Tiếp tục triển khai runtime SeaweedFS

**Cập nhật 12/11/2026:** xem [PostgreSQL Platform Docker](PLATFORM_FILER_POSTGRES_2026-11-12.md) và [runbook hiện hành](../infra/seaweedfs/README.md). Không còn chờ tạo role trên Windows. Phần dưới và [bàn giao cũ](BLUEDRIVE_BAN_GIAO_TASK01.md) giữ lịch sử ngày 10/11; quyền xóa/cutover cũ không áp dụng cho nhiệm vụ PostgreSQL mới.

Ngày 10/11/2026. **Chưa cutover; đang chờ tạo role PostgreSQL metadata bằng phiên admin đã lưu.**

## Đã xác minh và thực hiện

- Python 3.12.10 đã có ở đường dẫn mà `.venv` sử dụng. `.venv/Scripts/python.exe --version` và `pip check` đạt. Không cần cài lại hoặc tái tạo virtualenv.
- Docker Desktop **4.95.0**, Docker Engine **29.8.2**, Compose **5.6.0**, Linux engine chạy trên WSL 2. Docker nằm trong bản cài per-user; PATH của tiến trình sandbox cũ không phản ánh môi trường hiện tại. Docker đã có trong User PATH; Python dùng launcher `py` và `.venv`.
- `docker compose ... config --quiet` đạt. Đã pull image `chrislusf/seaweedfs:4.53`, thực thi được `weed version`: `30GB 4.53 4ab66fb76 linux amd64`. Đã lưu help CLI bốn thành phần; `-h` trả exit 2 theo CLI này, không phải bằng chứng lỗi khởi động.
- Digest đã tải: `sha256:ccad23e18639c8b98cee17e7100b95830a06077b56d8e5b006d6dcf8ec5e94a0`.
- **Master và Volume đang chạy, healthcheck healthy.** Master nhìn thấy đúng Volume với capacity 32. Không publish các admin port lên Windows host.
- Network SeaweedFS kết nối TCP được tới PostgreSQL host cổng 5432. Chưa thay `pg_hba.conf`, firewall hoặc cấu hình bảo mật Windows.
- Role PostgreSQL trong hai cấu hình dự án có CREATEDB, không có CREATEROLE/superuser. Không có libpq passfile/admin credential dùng được qua CLI.
- Đã mở pgAdmin và dùng phiên admin đã lưu để chạy truy vấn chỉ đọc: role admin có superuser/CREATEDB/CREATEROLE. Không lấy hoặc hiển thị mật khẩu admin.
- Đã kiểm tra **31/31 object MinIO khớp SHA-256**, tổng **5.693.666 byte**, không có upload đang hoạt động. Không có object mã hóa legacy trong tập 31 location hiện tại. Chưa sao chép, ghi hoặc xóa object.

Giống như kiểm tra kho mới: điện và đường vào đã có, nhưng cần cấp chìa khóa database riêng trước khi vận hành Filer/S3.

## Điểm đang chờ

Role `seaweedfs_filer` và DB `seaweedfs_meta` chưa tồn tại ở lần kiểm tra cuối. Hộp thoại Open native của pgAdmin không ổn định với công cụ tự động hóa: accessibility trả focus cũ, thao tác indexed field báo `element ... is not available in cached app state`. Đã chuyển sang luồng mở file chuẩn và yêu cầu người dùng hoàn tất đúng bước tạo role.

Người dùng cần mở file private `infra/seaweedfs/.local/bootstrap-role.sql` trong Query Tool admin và nhấn F5. File này chỉ tạo role Filer mới, chứa credential development đã sinh nên không gửi nội dung vào chat/issue. Sau khi role có, tiếp tục tạo database metadata riêng, khởi tạo schema bằng chính tài khoản Filer rồi chạy đủ bốn dịch vụ.

Một đề xuất cấp quyền đọc file bootstrap cho tài khoản sandbox đã bị automatic approval review **từ chối** do mở rộng quyền tới file chứa credential. Quyền đó **chưa được áp dụng**. Không giải mã kho mật khẩu hoặc vượt cơ chế bảo vệ; dùng thao tác mở file trong pgAdmin bằng tài khoản người dùng.

## Những bước chưa thực hiện

| Bước | Trạng thái |
| --- | --- |
| Python/Docker usable | PASS |
| Compose config, image/CLI | PASS |
| Master/Volume readiness và master thấy volume | PASS |
| PostgreSQL role/database/schema riêng | BLOCKED — chờ bootstrap admin |
| Filer/S3 startup/readiness | NOT RUN — phụ thuộc metadata DB |
| S3/multipart/checksum/presigned/resume integration | NOT RUN |
| Chrome CORS và finalizer thật | NOT RUN |
| Restart persistence | NOT RUN |
| Backup/restore kiểm tra phục vụ cutover | NOT RUN |
| Chuyển endpoint/metadata BlueDrive sang SeaweedFS | NOT RUN |
| Ngừng MinIO | NOT RUN — MinIO vẫn chạy bình thường |

Không đánh PASS runtime compatibility từ việc CLI hoặc hai container đã chạy. Người dùng đã cho phép bỏ các file thử nghiệm thay vì chuyển nguyên 31 file. Sau gate thật đạt, backup và xác minh bản restore trước khi reset có phạm vi, giữ tài khoản/workspace/audit và đối chiếu quota/sharing/FK; chỉ ngừng MinIO sau khi kiểm tra lại BlueDrive trên SeaweedFS.

## Bằng chứng

`docs/task01-runtime-evidence/` chứa phiên bản Python/pip check, image digest, CLI help, trạng thái container, Volume status và tổng kiểm tra SHA-256 nguồn. Không chứa `.env`, password hoặc presigned URL.

Các cấu hình và lệnh triển khai đầy đủ: [SeaweedFS runbook](../infra/seaweedfs/README.md). Báo cáo lượt trước là lịch sử: [Task 01](BLUEDRIVE_SEAWEEDFS_TASK01.md).
