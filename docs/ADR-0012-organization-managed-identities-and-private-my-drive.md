# ADR-0012 — Organization identity và My Drive riêng thuộc Tenant business

Ngày **17/11/2026**, Asia/Bangkok. Trạng thái: **chấp nhận cho P2 development** sau P1 development acceptance; chưa áp schema hoặc provisioning lên database phục vụ. Kế thừa [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md); không đổi storage routing, keys hoặc triển khai CSE.

## Vấn đề và bằng chứng

`accounts.signals` hiện tự tạo Personal Tenant cho regular User; `get_default_tenant` ưu tiên Personal, còn account snapshot có thể chọn business membership khác. Membership bị suspend/revoke không được làm employee quay về Personal. Organization directory hiện chỉ đọc và chưa có account provisioning.

File/folder listing và quyền chia sẻ dựa vào Workspace. Cho nhân viên dùng chung business General workspace như My Drive sẽ trộn quyền nội dung. Một membership có thể bị thu hồi/xóa; cờ gắn riêng trên membership không đủ giữ ownership identity lâu dài.

Giống hồ sơ nhân sự và ngăn tủ: công ty sở hữu hồ sơ, mỗi người có ngăn riêng; thu hồi thẻ ra vào không được biến hồ sơ thành tài sản cá nhân hoặc mở các ngăn khác.

## Quyết định

1. **Tenant business là Organization duy nhất.** Thêm `OrganizationIdentity` OneToOne với User, home Tenant business và provenance invitation. Identity chỉ ghi ownership bền vững; không tạo Organization model thứ hai hoặc role/status song song. User active/password và Membership role/status tiếp tục là nguồn cấp quyền. User/Tenant/identity đang được dữ liệu tham chiếu được bảo vệ khỏi hard delete.
2. **My Drive riêng dùng Workspace hiện có.** Workspace có nullable OneToOne `owned_identity`, không phải tenant default. Ràng buộc uniqueness và cùng Tenant bằng PostgreSQL composite FK theo pattern migration hiện có. Existing Personal/default workspaces giữ NULL; không backfill hoặc di chuyển data/user cũ. Owner employee có quyền nội dung riêng; quyền quản lý Organization hoặc Platform không tự cấp quyền đọc My Drive người khác. Explicit shares dùng policy hiện có.
3. **Canonical context, fail closed.** Explicit Workspace selector phải được parse/authorize trước default lookup. Không có selector, managed identity dùng own My Drive trong home Organization. Thiếu/inactive/revoked membership hoặc identity không đầy đủ phải deny, không lấy General/first membership/Personal fallback. Unmanaged Platform Personal behavior giữ nguyên; không chuyển account đã tồn tại thành managed account.
4. **Provisioning mới, transactional và idempotent.** Platform Admin tạo business Tenant + initial Org owner/admin; active Org owner/admin tạo employee MEMBER mới. Username/email conflict trả 409, không attach/promote/reset tài khoản cũ. Initial inactive User có unusable password; trusted internal signal skip chỉ dùng trong transaction tạo durable identity. Request key/digest nằm trên Tenant/Identity để retry không tạo trùng; replay vẫn kiểm quyền hiện hành. Không dựng provisioning-job abstraction.
5. **Invitation giữ nguyên bất biến bảo mật.** Reuse email locking, password validators, Django token/signing, session/CSRF, invitation/email transport gate đã có. Người nhận tự đặt password qua one-time activation; không trả token/password trong management API hoặc log. Link mới dùng URL fragment ở frontend để token không nằm trong HTTP query/referrer. Reinvite chỉ dành account managed pending được cấp quyền; activation lock identity/User/Membership và recheck trạng thái.
6. **Quota thuộc Organization.** Initial Tenant và Member quotas là finite explicit nonnegative limits; không mặc định unlimited hoặc mượn Personal/Workspace plan cho enterprise budget. Reuse QuotaAccount, quota services/audit và Tenant + Member accounting của business My Drive. Owned My Drive không nhận Workspace starter quota, không xuất hiện như collaborative workspace hoặc cho sửa membership/archive qua API workspace thường. Collaborative quota/permissions hiện có giữ nguyên.
7. **Offboarding bảo toàn dữ liệu.** Suspend/revoke/restore dùng membership workflow có sẵn; managed identity bị thu hồi không fallback Personal. Giữ User/Identity/Workspace/File/Version/quota/audit, không hard delete, transfer ownership hoặc purge. Chỉ thao tác tài khoản mới thuộc đúng Organization; không thay credential/user thật trong development verification. Last-admin/self-escalation safeguards giữ nguyên.

## Phương án so sánh

| Phương án | Đánh đổi / kết luận |
| --- | --- |
| Cờ managed trên Membership | Ít cột nhưng mất marker khi membership bị xóa; cần nhiều guard ngầm. Chọn identity ownership bền vững. |
| Dùng General cho tất cả employee My Drive | Ít schema nhưng Workspace ACL/listing làm lộ nội dung giữa nhân viên. Loại bỏ. |
| Thêm owner filters vào mọi file/folder API | Phạm vi rộng và dễ bỏ sót; reuse ranh giới Workspace riêng đã có. |
| Convert user/Personal Tenant hiện hữu | Ownership và offboarding có hậu quả dữ liệu; ngoài P2 development scope. Chỉ tạo identity mới. |
| Auto provision/bind Enterprise storage | Nhầm identity readiness với storage readiness; không thực hiện. Upload tiếp tục fail closed khi thiếu binding. |

## Giới hạn, validation và rollback

P2 code nằm trong checkout/branch riêng từ P1 accepted tip; runtime P1 không tự reload. Schema additive chỉ apply trên PostgreSQL test UUID có marker/role/port guards. Không migrate serving database, bật runtime rollout hoặc thay email/storage credentials. Fixture mail dùng locmem, không gửi invitation thật hoặc đăng nhập account thật.

Gửi invitation sau mọi ghi audit/DB và dựng response; lỗi gửi mail rollback tài nguyên mới. SMTP và PostgreSQL commit vẫn không atomic: nếu commit cuối thất bại sau khi mail được nhận, link không dùng được và operator cần retry. Giữ giới hạn này rõ ràng; P2 chưa có nhu cầu thêm outbox/worker chỉ để thay workflow invitation hiện có.

Kiểm thử phải bảo vệ inactive/anonymous/CSRF, Tenant/Workspace isolation, private employee My Drive, explicit/ambiguous/revoked context, idempotent conflict/retry, finite quota và offboarding retention; giữ full P1 regression và provider SKIP riêng. Shared auth/context/quota thay đổi cần full PostgreSQL regression; UI dùng Poppins/theme/primitives hiện có, không thêm UI library.

Rollback development bằng bỏ commit P2 sau review trên checkout riêng. Không rollback dữ liệu bằng drop/flush hoặc áp reverse migration vào serving. Production rollout/migration, data conversion, recovery/transfer và destructive retention cần gate riêng; quyết định này không cấp quyền thực hiện chúng.
