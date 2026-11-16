---
name: bluedrive-storage-validation
description: Plan and run BlueDrive storage compatibility gates for the MinIO to SeaweedFS transition, multipart, SHA-256, presigned URLs, browser CORS, resume, pinned versions and finalizer integrity. Use for real storage qualification or a storage contract change; it does not authorize cutover or destructive operations.
---

# Nghiệm thu storage BlueDrive

## Mục tiêu và khi dùng

Phân biệt regression adapter với bằng chứng provider thật, chọn đúng gate và tránh làm hỏng dữ liệu đang sử dụng. Áp dụng khi nghiệm thu SeaweedFS hoặc thay contract storage/upload/download/finalizer.

Đọc [AGENTS.md](../../../AGENTS.md), phần infrastructure trong [MAP.md](../../../MAP.md), [runbook SeaweedFS](../../../infra/seaweedfs/README.md) và [bàn giao Task 01](../../../docs/BLUEDRIVE_BAN_GIAO_TASK01.md). Runbook sở hữu lệnh; skill này sở hữu cách chọn, đánh giá và dừng gate.

## Quy trình

1. Xác minh môi trường, endpoint/public signer, bucket, namespace test, quyền ghi/dọn fixture và trạng thái runtime hiện tại bằng bằng chứng không chứa secret. Chưa đủ thông tin hoặc quyền thì BLOCKED gate phụ thuộc, vẫn tiếp tục kiểm tra source/config độc lập. Không in `.env`, `s3.json`, `filer.toml`, credential hay presigned URL.
2. Tách hai loại metadata: PostgreSQL Django giữ nghiệp vụ/quyền/quota/audit; PostgreSQL Filer giữ `filemeta` nội bộ SeaweedFS và dùng role/database riêng. Không cấp Filer tài khoản DB ứng dụng/admin hoặc tự mở rộng ACL/DB grants. Config generator test chỉ dùng thư mục tạm; không chạy lại generator trên `.local` đang dùng.
3. Chạy regression adapter/factory và unit config liên quan trước. Nếu cần provider thật, xác minh Master/Volume/Filer/S3, Master thấy Volume và đăng nhập metadata đúng role. Anonymous 403 là kiểm tra deny, chưa chứng minh signed readiness.
4. Bucket bootstrap dùng operator chỉ khi đã xác minh bucket chưa tồn tại và phạm vi cho phép. Không chạy lại `init-bucket` mù quáng, không thay CORS/versioning/policy bucket đang dùng để ép test pass. Các request ứng dụng dùng identity giới hạn bucket.
5. Chọn gate thật theo thay đổi, theo lệnh runbook: S3 PUT/GET/HEAD/DELETE/range/metadata; multipart part receipts/ListParts/resume/complete lặp/abort; presigned đúng/sai/hết hạn; SHA-256 toàn file, part checksum và composite semantics; conditional copy, version-pinned read/delete; deny anonymous/credential sai/cross-bucket.
6. Đường browser phải qua Chrome CORS thật với đúng origin/host đã ký, required headers và ETag/checksum đọc được. Không rewrite host sau ký. Đường finalizer phải chạy upload API → S3 thật → worker → download/quota trên test DB riêng, gồm file rỗng và hash sai; mock hoặc class bị skip không đóng gate.
7. Persistence yêu cầu ghi probe có manifest riêng, restart chỉ đúng bốn dịch vụ SeaweedFS đã được cho phép, rồi xác minh nội dung/version và `filemeta` còn dữ liệu. Không restart MinIO hoặc dịch vụ khác như một phần dọn test. Nếu restart chưa được phép, đánh BLOCKED riêng gate này.
8. Chỉ dọn đúng object/version/upload/probe do bài test tạo và có định danh xác minh; lỗi cleanup phải báo rõ. Giữ MinIO và dữ liệu nguồn đến khi Task 01 nghiệm thu. Skill không thực hiện backup/reset/cutover, bật rollout flag, dừng MinIO hoặc các Task 02/03 của lộ trình storage; những việc đó cần phạm vi và gate riêng.

## Hoàn thành và báo cáo

Mỗi gate yêu cầu phải có bằng chứng thực thi; thiếu checksum/conditional/version behavior thì FAIL hoặc BLOCKED, không hạ integrity requirement. Unit/config xanh không thay signed S3, browser, worker hoặc persistence. Harness Task 2 là công việc quy trình, không phải quyền bắt đầu Task 02 trong lộ trình storage.

Báo bảng gate → môi trường/phiên bản → lệnh → số bài pass/fail/skip → PASS/FAIL/SKIP/BLOCKED → hạn chế. Ghi trạng thái cleanup và blocker tiếp theo; không chép output chứa secret hoặc URL ký. Không kết luận đã cutover từ việc bộ test đã chạy.
