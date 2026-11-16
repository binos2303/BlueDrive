# Storage Control Center — S0 và hồ sơ gate G0

Ngày: 08/11/2026. Đầu vào: `BlueDrive_Storage_Control_Center_AZ_2026-11-08.zip`.

## Kết quả và phạm vi

Đã đọc toàn bộ 15 entry của ZIP, đối chiếu đủ 14 hash trong MANIFEST, kiểm kê source hiện tại và hoàn thành baseline khả dụng. Đã khai báo bốn cờ triển khai OFF trong settings và `.env.example`. Chưa tạo domain cluster/node, chưa thay routing upload/download, chưa cài React Flow/agent/MinIO, chưa chạy provisioning.

**S0 đã có hồ sơ kiểm chứng; G0 đang chờ chủ sở hữu duyệt và giải quyết đầu vào lab. S1–S8 chưa triển khai.** Không coi số test xanh hiện có là bằng chứng các tính năng trong lộ trình đã tồn tại hoặc đã an toàn để triển khai production.

Quy định đi tuần tự nằm ở `00_START_HERE_WINDOWS.md`, mục3: “Phê duyệt gate G0 trước khi giao Prompt 1.” `09_CODEX_PROMPTS.md` còn yêu cầu không chạy các sprint cùng lúc và dừng thao tác hạ tầng khi thiếu edition/license/disks/credentials thật. Skill đi kèm yêu cầu hoàn tất gate trước thay đổi và xác nhận của chủ sở hữu theo gate. Hồ sơ này là kết quả cụ thể để duyệt, không phải một yêu cầu phê duyệt dựa trên kế hoạch chưa kiểm tra.

Skill đã áp dụng:

- `ponytail`: giữ thay đổi S0 nhỏ, tái sử dụng công cụ DB riêng và test hiện có.
- `bluedrive-storage-control-center` trong ZIP: giữ trình tự gate, kiểm chứng source, phân loại bằng chứng và tương thích legacy.
- `impeccable`: đối chiếu UI hiện tại, kiểm tra route ở hai viewport, xem screenshot topology; chưa dùng hướng dẫn chỉnh UI vì chưa chỉnh UI.
- `humanizer`: rà cách viết báo cáo để nêu đúng việc đã làm, hạn chế và quyết định cần duyệt.

Không gọi các skill tạo ảnh/slide/bảng tính, điều khiển Office hoặc dịch vụ khác vì những việc đó không thuộc hạng mục S0. Không cài skill hoặc plugin toàn cục.

## Source map hiện tại

| Nghiệp vụ | File và symbol | Đã xác minh / chênh lệch với lộ trình |
|---|---|---|
| Organization | `backend/accounts/models.py:8`, `Tenant` | Chỉ có kind personal/business; chưa có kind/scope owner riêng cho Platform storage. Không tạo thêm Organization model trùng Tenant. |
| Vai trò tổ chức | `accounts/models.py:61`, `Membership`; `accounts/access.py` | Owner/admin/member có trạng thái; chưa có `storage_admin` hoặc grant storage riêng. Quyền hạ tầng không được biến thành quyền đọc nội dung. |
| Platform Admin | `accounts/platform_admin.py:9` | Bootstrap staff superuser hoặc active dedicated PlatformAdminIdentity. Không dùng `is_staff` đơn lẻ làm quyền Platform. |
| Provision Organization | `accounts/admin_api.py:192`, `admin_organizations_view` | Endpoint hiện chỉ GET directory; chưa có API tạo Organization/cấp Owner/suspend Organization như mục tiêu lộ trình. User tự tạo Organization cũng chưa có trong routes đã kiểm tra. |
| Organization quota | `accounts/organization_quota_api.py:31` | Đã có GET/PATCH tenant-scoped; owner/admin của business active được quản lý quota tenant/member/workspace. Không xóa module này hoặc đưa quota doanh nghiệp về Platform. |
| Storage connection metadata | `files/models.py:280`, `StorageConfig` | Có tenant/provider/status/endpoint/credential_ref, unique tenant+provider; chưa lưu đủ cấu hình kết nối versioned cho đa cluster. Giữ constraint ở MVP. |
| Object location | `files/models.py:332`, `StorageLocation` | FK storage_config, provider_version_id đã có. Không được sửa ref file cũ chỉ vì binding mới active. |
| Upload session | `files/models.py:405`, `UploadSession` | Chưa có FK storage_config hoặc endpoint_config_version; chưa ghim target storage theo session. |
| Worker | `files/models.py:534`, `UploadFinalizationJob`; `files/finalization.py`; command `finalize_uploads` | Có claim/attempt và stale threshold; hiện vẫn dùng adapter từ settings toàn cục. |
| Adapter factory | `files/storage_adapters/factory.py:7` | **Không phải singleton cache** như cách diễn đạt trong plan: mỗi call tạo adapter mới, nhưng luôn đọc cùng settings global. DI/resolver vẫn còn thiếu. |
| Organization UI | `frontend/components/organization/OrganizationAdminPage.tsx:49,267` | Chỉ Workspaces/Members; chưa có Storage. Route hiện tại `/organization/admin`. |
| Platform topology | `frontend/app/(admin)/admin/infrastructure/topology/page.tsx:9` | Placeholder trung thực “Topology telemetry not connected”; chưa có canvas hoặc node thật. Route chưa được quảng bá trên nav chính. |
| Design system | `components/ui`, `app/globals.css`, layout AdminConsole | Dùng token chung light/dark, Button/Dialog/DataTable. StorageManager tương lai phải dùng lại, không dựng một hệ giao diện riêng. |
| Dependency React Flow | `frontend/package.json` | Chưa có `@xyflow/react`; chưa cài ở S0. |
| Feature gates | `backend/securedrive/settings.py:159` | Đã thêm bốn cờ OFF trong lượt này; chưa có handler SCC sử dụng chúng. Cờ đơn lẻ chưa phải security policy. |

## Call graph phải giữ đồng bộ khi tới S2

```text
Upload create/idempotent retry
  -> files.upload_api._initialize_upload_session
  -> quota reservation + global get_storage_adapter
Part authorization / reconciliation / abort / status
  -> files.upload_api -> global adapter
Complete
  -> UploadFinalizationJob -> finalize_uploads -> files.finalization
  -> verify/publish -> StorageLocation(storage_config, provider_version_id)
Download/presign/preview
  -> files.views -> current StorageLocation -> global adapter
Copy/duplicate
  -> dashboard.drive_api -> global adapter
Expiry/cleanup
  -> cleanup_uploads -> global adapter
Permanent delete
  -> files.permanent_delete -> global adapter
```

Thay riêng factory hoặc thêm form endpoint chưa đủ để multi-cluster hoạt động. Session cần chọn target một lần; file cũ cần đọc đúng StorageLocation. Giống địa chỉ trên phiếu gửi hàng: đổi địa chỉ mặc định cho đơn mới không được đổi nơi nhận của kiện hàng đã gửi.

## Thay đổi đã áp dụng

1. `backend/securedrive/settings.py`: thêm bốn cấu hình boolean mặc định False:
   - `SECUREDRIVE_STORAGE_CONTROL_CENTER_ENABLED`
   - `SECUREDRIVE_STORAGE_MULTI_CLUSTER_ROUTING_ENABLED`
   - `SECUREDRIVE_STORAGE_AGENT_OPERATIONS_ENABLED`
   - `SECUREDRIVE_STORAGE_DESTRUCTIVE_OPERATIONS_ENABLED`
2. `backend/.env.example`: tài liệu hóa cả bốn cờ ở false. Không sửa `.env` thật. Tên cờ chỉ chuẩn bị cho rollout; chưa có API SCC hoặc agent để kích hoạt.
3. `docs/roadmaps/storage-control-center-2026-11-08/`: lưu nguyên bộ hướng dẫn làm đầu vào có hash, không sửa nội dung theo trạng thái triển khai.
4. Báo cáo này, bảng tiến độ và artifact S0: source checkpoint, secret scan dạng số lượng/boolean, test log, screenshot, feature flag check. Không chép auth state hoặc config chứa secret vào bộ bằng chứng.

Không reset, clean, stash, commit hoặc tự chuyển nhánh. Working tree đang trên `main`, có 227 entry tại checkpoint sau khi thêm tài liệu; nhiều thay đổi có từ công việc trước. Không ghi đè các thay đổi đó. Nhánh/PR theo sprint chưa được tạo; đây là điều cần thống nhất khi duyệt G0, thay vì coi working tree hiện tại là một baseline Git sạch.

Không có migration mới; không apply migration lên database ứng dụng. Lệnh kiểm tra dry-run ghi `No changes detected`.

## Kiểm thử thực tế

| Kiểm tra | Kết quả | Điều kiện / bằng chứng |
|---|---|---|
| Django full suite | **448 phát hiện, 439 PASS, 9 SKIPPED** | PostgreSQL18.6 cluster mới, 59,193s; `backend-baseline.txt` |
| DB isolation | PASS | Data directory đúng cluster mới, DB test chưa tồn tại, role/password mới, loopback, dừng và xóa cluster; `backend-isolation.json` |
| Storage/email isolation | PASS trong runner | Chặn botocore HTTP ngoài mock, MEDIA_ROOT tạm, email locmem; không gọi MinIO thật từ suite |
| Node unit | **152 PASS, 0 FAIL, 0 SKIP** | 37 file, khoảng1,40s; `frontend-node-tests.txt` |
| TypeScript | PASS | `tsc --noEmit`, exit0 |
| ESLint toàn frontend | PASS | `eslint .`, exit0 |
| Next production build | PASS | Bản sao source riêng, Next16.3.3 `--webpack`; compile26,4s, generate38/38; không đụng `.next` dev đang dùng |
| Chrome Platform baseline | **4 PASS** | Organization directory và topology, desktop/mobile, API mock |
| Chrome Organization Admin | **4 PASS** | Confirmation lỗi role và bỏ phản hồi cũ, desktop/mobile, API mock |
| Django check sau flags | PASS | Không có system-check issue |
| Migration dry-run sau flags | PASS | Không có thay đổi schema cần migration |
| Feature flag acceptance | PASS | AST xác nhận cả4 defaultFalse và settings local đều False; không mở DB/storage trong bước này |
| Diff whitespace | PASS | Hai file application được sửa trong lượt này |

Lượt backend đầu dùng hasher mặc định được dừng có chủ đích trước khi hết timeout; không coi là lỗi ứng dụng hoặc lượt suite hoàn tất. Runner đã dọn cluster đó, có `backend-aborted-isolation.json`. Lượt hoàn tất dùng MD5PasswordHasher **chỉ trong tiến trình test**; assertion/password policy không bị sửa, production hashers không đổi. Các kết quả trước đây của kit A01–A12 vẫn giữ nguyên, không được xóa vì full suite hiện có xanh.

Build dùng snapshot trong thư mục test-results để không ảnh hưởng dev server. Không chép `.env`, `.auth`, CLI config hoặc node_modules data vào snapshot; dependency dùng junction tới bản đã cài. Có warning Next chọn workspace root vì lockfile lồng; build exit0. Không đổi next.config chỉ để xóa warning trong snapshot.

Chrome sử dụng mock API, không đăng nhập hoặc gửi mutation tới account thật. Đã xem screenshot desktop topology; UI hiện tại chưa có node/canvas, nên chưa thể đo 50/100-node FPS, drag persistence, inspector hoặc telemetry.

## Phát hiện S0 cần xử lý

### 1. Source ZIP cũ có auth state khớp file local

Quét nội dung `BLUEDRIVE_SOURCE_AUDIT_SAFE.zip`, không chỉ tên file:

- `source/frontend/playwright/.auth/admin.json`: hai cookie có giá trị không phải placeholder, chưa quá timestamp expiry; cả hai giá trị khớp file auth local hiện tại.
- `source/frontend/playwright/.auth/user.json`: cùng kết quả hai cookie khớp local.
- `source/frontend/.cache/storage-tools/mc-config/config.json`: ba alias có credential không rỗng/không phải placeholder theo bộ phân loại. **Không alias nào khớp cặp credential ứng dụng hiện tại** trong `.env`; chưa xác minh đó là credential cũ, mặc định công khai hay còn hiệu lực. Không coi cả ba là secret production đã xác nhận.

Không in, sao chép hoặc dùng credential từ ZIP để truy cập dịch vụ. Timestamp chưa hết hạn không chứng minh session server còn hiệu lực. Báo cáo chỉ lưu count/boolean. Cần chủ sở hữu quyết định thu hồi các session đã xuất và phân loại/rotate credential thực còn hiệu lực trước khi chia sẻ lại ZIP cũ. Không tự đăng xuất các phiên người dùng đang sử dụng hoặc thay credential khi chưa có mapping/runbook.

Các đường dẫn này đã được `.gitignore` loại trừ. ZIP cũ vẫn chứa chúng vì cơ chế xuất nguồn đã không tôn trọng vùng loại trừ; cần kiểm tra nội dung artifact sau đóng gói, đồng thời giữ đủ `.test.mts`. Lượt này không tạo lại hoặc chia sẻ ZIP source cũ.

### 2. Điều kiện lab/edition chưa có bằng chứng

`backend/minio-compose.yml` pin `RELEASE.2025-04-22T22-12-26Z`, volume `minio_data` cố định. Đây là cấu hình source, chưa phải xác nhận phiên bản hoặc số node thực chạy. Không có Docker trong PATH và đường cài mặc định đã kiểm tra không tồn tại.

Có `mc.exe` local. Bước inventory chỉ đọc tìm alias local hiện tại khớp endpoint, không dùng credential đã xuất; kết quả `NOT_RUN_NO_MATCHING_LOCAL_ALIAS`. Không tìm alias root khác để tăng đặc quyền, không thử deploy hay fault trên dịch vụ đang dùng. `minio-readonly-inventory.json` ghi rõ chưa xác minh isolation/license.

Đối chiếu nguồn chính thức: repository Community đã được owner archive ngày25/04/2026, license AGPLv3; điều này không tự chứng minh license hoặc edition của instance hiện tại. [MinIO repository](https://github.com/minio/minio). Runbook AIStor là tài liệu của sản phẩm riêng và mở rộng theo pool cần chọn đúng phiên bản. [AIStor scaling](https://docs.min.io/aistor/operations/scaling/).

React Flow có tài liệu cho client graph, custom nodes, accessibility, performance và sub-flows; sẽ đối chiếu lại API/version khi S3 bắt đầu, chưa pin dependency trước khi tới sprint đó. [React Flow documentation](https://reactflow.dev/learn).

### 3. Baseline xanh chưa bao phủ các bất biến đã FAIL

Kit A01–A12 đã chạy trong lượt trước xác nhận các vấn đề status/khởi tạo upload/xóa metadata, shared ZIP, subtree permission, unbounded read và pagination gap; xem `docs/AUDIT_KIT_RESULTS_2026-11-08.md`. Không sửa chúng trong S0 vì Prompt0 yêu cầu kiểm toán trước. G0 cần quyết định rõ remediation hoặc giới hạn S1 chỉ inventory, feature OFF, không đổi data plane. Không dùng 439 test xanh để xóa các phát hiện độc lập này.

### 4. Ownership Platform storage cần chốt trong thiết kế S1

Plan yêu cầu cluster có tenant owner, nhưng Tenant hiện chỉ personal/business. Không gắn cluster Platform với tài khoản cá nhân ngẫu nhiên hoặc giả làm một Organization doanh nghiệp. S1 cần một phương án owner scope có constraint và migration rõ ràng; phải kiểm tra mọi query dựa vào Tenant.Kind và không để người dùng tự cấp scope Platform. Có thể đề xuất ADR cụ thể trong S1; chưa tạo model để lấp khoảng trống bằng giả định.

## Gate G0 và đề xuất bước tiếp

| Điều kiện | Trạng thái |
|---|---|
| Đọc/verify hướng dẫn và đối chiếu source | PASS |
| Baseline backend/Node/TS/lint/build/browser khả dụng | PASS, có9 integration skip |
| Test isolation và cleanup | PASS |
| Bốn rollout switches mặc định OFF | PASS |
| Working tree sạch / branch sprint được xác nhận | Chưa đạt: giữ nguyên dirty tree, chưa tự tạo branch |
| Rủi ro source ZIP được xử lý/accepted | Chờ chủ sở hữu; auth state khớp local, chưa revoke |
| MinIO lab riêng, edition/version/license/topology đã xác minh | BLOCKED: chưa có bằng chứng môi trường riêng |
| G0 được chủ sở hữu duyệt | PENDING |

Đề nghị duyệt hồ sơ S0 và cho phép bắt đầu **S1 inventory/RBAC độc lập, mặc định OFF**, chưa đổi upload/download và chưa vận hành MinIO. Những điều kiện cần lab/license sẽ tiếp tục BLOCKED tới khi có môi trường phù hợp; không kích hoạt S2 verify/S4 collector/S5 agent/S6 deploy trên instance chưa xác định.

Các sprint còn lại giữ nguyên thứ tự trong plan. Không đánh dấu S1 hoặc React Flow là hoàn tất khi chỉ mới tạo feature flags. Không triển khai hàng loạt S0–S8 trong một lệnh tự động vì tài liệu yêu cầu gate theo sprint.

## Rollback của thay đổi S0

Giữ bốn cờ false là trạng thái an toàn hiện tại; chúng chưa điều khiển một handler SCC nào. Nếu cần bỏ khai báo S0, chỉ gỡ đúng block bốn settings và bốn giá trị `.env.example` đã thêm trong lượt này. Không dùng `git checkout` cả file vì các file có thay đổi khác từ trước. Không cần rollback schema hoặc object; không có migration/data operation mới.

Hướng dẫn gốc, báo cáo và artifact có thể giữ làm lịch sử. Build snapshot không phải bản triển khai. Không phát hành hoặc cài agent/MinIO từ bộ tài liệu này.

## Evidence và bàn giao

Workspace: `frontend/test-results/storage-control-center-s0/`. Báo cáo, log được xuất vào Downloads `BLUEDRIVE_SCC_S0`; chỉ copy danh sách artifact đã chọn, không copy build snapshot/junction/auth/config.

File chính: `backend-baseline.txt`, `backend-isolation.json`, `frontend-node-tests.txt`, `frontend-build.txt`, `checks-summary.json`, `feature-flags.json`, `s0-inventory.json`, `minio-readonly-inventory.json`, screenshot route baseline và `evidence-manifest.json`. `SPRINT_PROGRESS.csv` thể hiện phần đã làm và các sprint chưa bắt đầu.

Skill tái sử dụng đã có trong gói tại `docs/roadmaps/storage-control-center-2026-11-08/agent-skill/SKILL.md`; tiếp tục sử dụng theo gate. Chưa cần viết thêm một skill tương tự hoặc tự cài nó vào cấu hình Codex toàn cục.
