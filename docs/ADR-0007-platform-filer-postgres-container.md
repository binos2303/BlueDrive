# ADR-0007 — PostgreSQL container riêng cho Platform Filer

Ngày: 12/11/2026, Asia/Bangkok. Trạng thái: **đã triển khai trong môi trường development theo yêu cầu người dùng**; chưa cutover, chưa nghiệm thu toàn bộ SeaweedFS Task 01.

## Vấn đề

Platform Master/Volume đã chạy nhưng Filer/S3 chờ bootstrap PostgreSQL trên Windows. Enterprise Lab đã có DB riêng và không được dùng chung. Việc tạo role thủ công trên host làm bootstrap phụ thuộc thao tác ngoài Compose.

## Quyết định

Thêm `postgres:17-alpine` vào Compose project `bluedrive-seaweedfs`, dùng named volume `postgres_data` và network `storage` của riêng project; không publish PostgreSQL ra host. Filer kết nối `postgres:5432`, chỉ bật backend PostgreSQL và dùng role metadata có quyền hạn chế. Tài khoản `postgres` chỉ bootstrap, có mật khẩu ngẫu nhiên riêng trong cấu hình local được ignore và bảo vệ bằng ACL hiện có.

Docker entrypoint chạy SQL đã sinh khi data directory mới: tạo database/role/schema và bảng `filemeta`. Giữ `createTable=false` để DDL thuộc bootstrap. Filer chờ PostgreSQL healthy qua TCP và Volume healthy; S3 chờ Filer, trỏ `filer:8888`, chỉ publish `127.0.0.1:8333`. Enterprise vẫn ở project/network/volume riêng và S3 :8433.

Giống hai tòa nhà có phòng cùng số: hostname `postgres` chỉ có ý nghĩa trong địa chỉ network riêng của mỗi project, không làm hai DB thành một.

## Phương án loại bỏ

- PostgreSQL Windows: cần bootstrap role và quản lý kết nối Docker–host thủ công; không đáp ứng yêu cầu triển khai bằng Docker.
- Dùng PostgreSQL Enterprise: vi phạm yêu cầu cách ly, tăng phạm vi ảnh hưởng khi restart/backup.
- Cho Filer dùng superuser hoặc tự tạo bảng: bỏ ranh giới quyền/DDL đang có, không cần thiết vì bootstrap SQL đã có sẵn.

## Hệ quả và rollback

Thêm một container và volume phải backup cùng dữ liệu SeaweedFS; cùng một máy không tạo HA. Tag `17-alpine` giữ major nhưng có thể đổi patch; digest runtime ghi trong báo cáo nghiệm thu. Init script chỉ chạy trên data directory mới; không xóa volume để chạy lại hoặc tự đổi credential của DB đã có.

Cấu hình private trước triển khai được giữ trong `.local/before-platform-postgres-20261112/`. Khi cần rollback phải kiểm tra và backup DB/object mới trước; có thể dừng đúng các service mới `s3 filer postgres` sau khi được phép, giữ mọi volume và probe. Khôi phục file cũ không đồng nghĩa PostgreSQL Windows đã sẵn sàng. Không chạy `down -v`, không thay Storage Connection Django, MinIO hoặc Enterprise.

## Nguồn và bằng chứng

- [PostgreSQL official image entrypoint](https://github.com/docker-library/postgres/blob/master/docker-entrypoint.sh).
- [Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/).
- [SeaweedFS 4.53 PostgreSQL store](https://github.com/seaweedfs/seaweedfs/blob/4.53/weed/filer/postgres/postgres_store.go).
- [Bằng chứng triển khai và giới hạn](PLATFORM_FILER_POSTGRES_2026-11-12.md).
