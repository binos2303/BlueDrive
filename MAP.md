# BlueDrive — bản đồ dự án

Đối chiếu bổ sung P2 development ngày **17/11/2026** từ P1 đã nghiệm thu trên nhánh riêng. Đọc [AGENTS.md](AGENTS.md) trước khi sửa, sau đó chọn module/tài liệu liên quan ở đây. [P0](docs/REFACTOR_P0_BASELINE_2026-11-16.md) giữ inventory/gaps lịch sử; [P1](docs/REFACTOR_P1_BASELINE_2026-11-16.md) ghi harness/build/CI và bằng chứng nghiệm thu. P2 chưa được migrate hoặc rollout lên database phục vụ; không suy runtime từ source hoặc báo cáo cũ.

## Stack và điểm vào

| Thành phần | Nguồn xác minh và điểm vào |
| --- | --- |
| Web | [frontend/package.json](frontend/package.json), [lockfile](frontend/package-lock.json): Next.js **16.4.6**, React/React DOM **19.2.8**, TypeScript lock **5.9.3**, Tailwind lock **4.3.3**, Playwright **1.65.0**; Next/eslint-config-next được vá có mục tiêu trong P4 ngày 18/11/2026. |
| Frontend runtime | `npm run dev/build/start`; [app/layout.tsx](frontend/app/layout.tsx) nạp theme, account và upload providers; [app/page.tsx](frontend/app/page.tsx) chuyển tới login. Next.js App Router tự khám phá page/layout, không cần import tường minh. |
| API | [backend/requirements.txt](backend/requirements.txt): Django **5.2.17**, DRF **3.18.0**, Psycopg **3.3.6**, boto3/botocore **1.43.112**. [manage.py](backend/manage.py) → [settings.py](backend/securedrive/settings.py) → [urls.py](backend/securedrive/urls.py); WSGI/ASGI trong cùng package `securedrive/`. |
| Database | Settings dùng `django.db.backends.postgresql`; mỗi Django app giữ models/migrations riêng. Application PostgreSQL local quan sát **18.6** bằng read-only query P0; không có manifest pin server ứng dụng. Filer PostgreSQL được Compose pin major **17-alpine** riêng từng cluster. |
| Object storage | Đích **SeaweedFS-only** qua adapter S3 chung, Platform/Enterprise độc lập theo [ADR-0010](docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md). [Platform Compose](infra/seaweedfs/compose.yml) và [Enterprise Compose](infra/enterprise-lab/compose.yml) pin SeaweedFS **4.53**, Filer metadata DB/role riêng. Provider=`s3`, Compose hoặc DB state ready không chứng nhận physical provider/runtime. |
| Môi trường dev | [infra/bootstrap-python.ps1](infra/bootstrap-python.ps1): CPython **3.12.10** NuGet ghim hash trong `.python/`, khôi phục **chính `.venv`** và giữ package; không đổi system Python/PATH. Fallback embeddable `.task01-runtime/python/` là lịch sử P0. Node/npm quan sát P1 **24.18.0 / 12.0.2**; không tạo `backend/venv`. |

Luồng chính: frontend → Django cấp quyền/session/quota → S3 staging → finalizer → metadata available; download qua backend hoặc presigned GET đủ điều kiện. PostgreSQL ứng dụng và object store không có transaction ACID chung.

## Frontend: tìm code theo chức năng

| Vị trí | Trách nhiệm / nơi bắt đầu |
| --- | --- |
| [frontend/AGENTS.md](frontend/AGENTS.md), [frontend/README.md](frontend/README.md) | Hướng dẫn Next.js theo phiên bản, setup và test scripts. `frontend/CLAUDE.md` hiện tham chiếu AGENTS cùng thư mục; không tạo thêm bản nội quy trùng. |
| `frontend/app/` | Route/layout: `(auth)/`, `drive/`, `drive/workspaces/[workspaceId]/`, `account/`, `organization/`, `(admin)/admin/`. Page điều phối component; nghiệp vụ/API client không dồn vào page. Route group trong ngoặc không phải URL segment. |
| `frontend/components/drive/` | `DriveFileBrowser`, `UploadManager`, upload service/model; `browser/` chứa list/grid, dialogs, helpers, selection/upload hooks và `SharedFolderContext`. |
| `frontend/components/account/`, `workspaces/`, `organization/` | Account context/settings, Workspace context/members/invites và Organization UI. `SelectedWorkspaceContext` và `useActiveWorkspaceId` ở `workspaces/`. |
| `frontend/components/admin/`, `storage/` | Admin directories/quota/infrastructure; Storage Control Center, topology và monitoring. Backend vẫn quyết định capability/scope. |
| `frontend/components/ui/`, `shared/`, `layout/`, `theme/` | Primitives và thành phần dùng chung: Button, Dialog, ContextMenu, DataTable, empty states, navigation/shell và theme provider. Tái sử dụng trước khi tạo biến thể. |
| [frontend/app/globals.css](frontend/app/globals.css), [frontend/lib/theme.ts](frontend/lib/theme.ts) | Token màu/control/motion, light/dark và khởi tạo theme. Đây là nơi đối chiếu design system thực tế. |
| [frontend/app/fonts/poppins/](frontend/app/fonts/poppins/README.md) | Poppins nguyên gốc 400/500/600/700 và OFL, nguồn/checksum được ghi; root layout dùng `next/font/local`, không fetch Google Fonts khi build. Giữ tokens/CSS variable hiện hữu. |
| `frontend/lib/` | API services và policy/query utilities: `account-service.ts` dùng chung request/session/CSRF; `drive-service.ts`, `workspace-service.ts`, `share-service.ts`, `storage-control-service.ts`; `workspace-context.ts`, `drive-paths.ts` giữ scope điều hướng. |
| [`frontend/lib/cse/`](frontend/lib/cse/), [`CseFixtureControls.tsx`](frontend/components/drive/CseFixtureControls.tsx) | Browser `cse_v1`, unlock và recovery Personal owner-only. Tích hợp với upload multipart và download hiện có. Chỉ bật UI fixture khi có public pin riêng và directory đã xác minh. |
| `frontend/hooks/`, `frontend/features/` | Đã có thư mục nhưng chưa có file nguồn tại lần kiểm kê (`features/` có các thư mục con rỗng). Logic/hook hiện chủ yếu nằm cạnh component và trong `lib/`; không mặc định chuyển code vào đây. |
| `frontend/types/`, `public/` | Kiểu dùng chung và static assets. Kiểu chỉ phục vụ một feature nên đặt cạnh feature hiện hữu. |

## Backend: module, API, dữ liệu và quyền

| Vị trí | Trách nhiệm / nơi bắt đầu |
| --- | --- |
| `backend/securedrive/` | Django settings, URL router, WSGI/ASGI, frontend redirects. Router chính include app routes; URL hiện không có namespace `/api/v1` chung như bản đề xuất cũ. |
| [test_settings.py](backend/securedrive/test_settings.py), [test harness guards](backend/tools/test_test_settings.py) | Settings test giữ process allowlist, không đọc dotenv/runtime credential; [target contract](backend/securedrive/test_environment.py) cố định local/CI và kiểm server marker trước tạo/hủy DB. Random test keys/media; giữ middleware/ACL/quota/constraints. Guards kiểm trực tiếp credential readers, target mutation và live confirmation/CI denial. |
| `backend/accounts/` | Tenant personal/business, Membership, Workspace/WorkspaceMembership, quota accounts/plans/policy và account/admin APIs. `access.py` xử lý membership/scope; `platform_admin*.py` phân tách platform admin. API nằm ở `api_views.py`, `workspace_api.py`, `admin*_api.py` và các `*_api.py` liên quan, được nối bởi `urls.py`. |
| `backend/accounts/organization_provisioning.py`, `organization_api.py` | P2 tạo Organization/managed account mới, lời mời activation, idempotency, quota/audit; reuse Tenant business, không tạo model Organization thứ hai. `OrganizationIdentity` giữ home ownership, `Workspace.owned_identity` phân tách My Drive riêng; `access.py` quyết định context/quyền nội dung. `workspace_api.py` quản lý `WorkspaceRemovalRequest` và Org Admin approval riêng cho removal business Workspace. Xem [ADR-0012](docs/ADR-0012-organization-managed-identities-and-private-my-drive.md) và [API addendum](docs/API_CONTRACT_V1.md#p2-organization-provisioning--2026-11-17). |
| `backend/files/` | File/FileVersion, StorageConfig/StorageLocation, UploadSession/UploadFinalizationJob/QuotaReservation. `upload_api.py` là API upload; `views.py`, `services.py`, `rename_service.py`, `permanent_delete.py` xử lý thao tác file; `quota.py` quản lý reservation/consumption/release; `finalization.py` xác minh/publication. |
| [`cse.py`](backend/files/cse.py), [`cse_api.py`](backend/files/cse_api.py), [`cse_fixture_settings.py`](backend/securedrive/cse_fixture_settings.py) | Manifest và authorization thiết bị, tải ciphertext đã ghim version, lưu recovery rewrap. Writer chỉ có trong settings fixture với marker PostgreSQL và bucket SeaweedFS riêng. |
| `backend/files/storage_adapters/`, [storage_routing.py](backend/files/storage_routing.py) | Contract/factory/S3-compatible adapter và resolve storage revision đã ghim; legacy có endpoint khác global bị từ chối. Tìm ở đây trước khi thêm provider hoặc đổi endpoint. |
| Cutover tooling lịch sử | `storage_cutover.py`, `audit_storage_cutover`, `migrate_platform_storage` được mô tả trong ADR-0008 nhưng **không có trong working tree P0**; không là entry point hiện hành. Kiến trúc mới không yêu cầu MinIO copy/cutover. |
| `backend/folders/` | Folder model, tree/list, thao tác thư mục, archive/ZIP; `tree_service.py`, `archive_service.py`, `views.py`, `urls.py`. |
| `backend/sharing/` | Share model, permission/inheritance policy và API/view cho chia sẻ; `services.py`, `policy.py` là điểm đọc trước khi đổi quyền hoặc download chia sẻ. |
| `backend/dashboard/` | Drive listing/search/recent/activity/shared views và `drive_api.py`; dùng scope và services hiện có, không tự mở rộng quyền từ truy vấn UI. `management/commands/seed_demo.py` là tác vụ ghi dữ liệu riêng, yêu cầu password do operator cấp và không in credential; harness không chạy seed. |
| `backend/security/` | AES-GCM legacy và SHA-256: `aes_service.py`, `hash_service.py`; không tự đổi key/format. |
| `backend/logs/` | ActivityLog và helper ghi audit trong `models.py`, `services.py`; không tạo kho audit thứ hai. |
| `backend/infrastructure/` | Storage Control Center: inventory/grants/bindings/revisions trong `models.py`; `api.py`, `connection_api.py`, `telemetry_api.py`, `urls.py`; profiles/connections/probes/telemetry/Prometheus trong các service tương ứng. Cờ rollout mặc định OFF ở settings. |
| `backend/<app>/models.py`, `migrations/`, `serializers.py` khi có | Models và migration của đúng app sở hữu nghiệp vụ; serializers chỉ nằm ở app cần chúng. Kiểm tra migration/DB constraint ngoài ORM, đặc biệt ràng buộc cùng tenant trên PostgreSQL. |
| `backend/<app>/management/commands/` | Worker và tác vụ vận hành. `run_upload_finalizer`, `finalize_uploads`, `cleanup_uploads`, quota reconciliation, probe cleanup và telemetry collection có thể thay trạng thái; đọc command/runbook trước chạy. Không dùng lệnh cutover lịch sử không còn trong source. |
| `backend/files/management/commands/report_upload_recovery.py` | Báo cáo chỉ đọc một upload. `--inspect-storage` kiểm tra đúng key và version đã ghi nhận tại đích gốc. Kết quả đối chiếu có thể thay đổi trong lúc worker chạy và cần xác minh trước khi xử lý. |
| `backend/templates/`, `static/`, `media/` | Templates/static của các Django views legacy; `media/` là nội dung runtime, có thể chứa ciphertext, không phải thư mục để dọn source. |

## Infrastructure, tests và scripts

| Vị trí | Trách nhiệm / giới hạn |
| --- | --- |
| [infra/seaweedfs/README.md](infra/seaweedfs/README.md), [compose.yml](infra/seaweedfs/compose.yml) | PostgreSQL 17/Master/Volume/Filer/S3, Docker network/volumes/health; PostgreSQL metadata có volume riêng, chỉ publish S3 loopback :8333. `.env.example` là mẫu; `.env` và `.local/` chứa cấu hình private, không ghi đè khi đã có. |
| `infra/seaweedfs/configure.py`, `test_configure.py` | Sinh và kiểm tra cấu hình development, credentials tách operator/app và metadata PostgreSQL riêng. Không phải lệnh cutover. |
| `infra/seaweedfs/smoke.py`, `browser-smoke.mjs` | Gate S3/checksum/multipart/presign/resume, Chrome CORS và persistence; ghi fixture theo cờ opt-in trong runbook. |
| [infra/seaweedfs/regression.py](infra/seaweedfs/regression.py), [test PostgreSQL Compose](infra/postgres-test.compose.yml) | Runner mặc định ép isolated settings, tám app/labels, DB UUID mới, chặn zero discovery/keepdb. Local test PostgreSQL 18.6 riêng trên tmpfs/loopback 55432, [init marker](infra/postgres-test-init.sql) read-only. Live chỉ nhận hai SeaweedFS provider classes/module alias đã duyệt; fixture bucket `bluedrive-test-<scope>`, credentials/endpoint loopback explicit; giữ test settings/media/email/DB. CI chặn mode live. |
| [infra/enterprise-lab/README.md](infra/enterprise-lab/README.md), [compose.yml](infra/enterprise-lab/compose.yml) | SeaweedFS doanh nghiệp mô phỏng, PostgreSQL Filer/network/volumes riêng, S3 loopback :8433. Cùng laptop không là HA; P0 chưa kiểm runtime Enterprise. MinIO Compose cũ đã bị xóa trong diff có sẵn; không suy runtime đã dừng/xóa. |
| `backend/files/tests/`, `backend/<app>/tests.py`, `test_*.py` | Backend unit/regression/security; integration S3 thật là opt-in. Không tạo test database bằng SQLite để thay chứng nhận constraint PostgreSQL. |
| `frontend/components/**/*.test.mts`, `frontend/lib/**/*.test.mts` | Node unit tests đặt cạnh component/helper; script `test:*` thực tế ở `frontend/package.json`. Không có script `npm test` chung tại lần kiểm kê. |
| [`frontend/experimental/cse/`](frontend/experimental/cse/), [`p6-personal-cse.live.spec.ts`](frontend/e2e/p6-personal-cse.live.spec.ts) | Harness WebCrypto/HPKE, directory với witness và custody prototype. Bài Playwright ứng dụng dùng Django/PostgreSQL/SeaweedFS loopback riêng và synthetic identities. [P6 Security Design](docs/REFACTOR_P6_SECURITY_DESIGN_2026-11-19.md) tách bằng chứng fixture khỏi phê duyệt bảo mật và serving. |
| [frontend/e2e/README.md](frontend/e2e/README.md), [playwright.config.ts](frontend/playwright.config.ts) | Playwright Chrome desktop/mobile, một worker, mục tiêu local; phân biệt mocked và live. Live dùng test accounts và chỉ dọn fixture của chính bài test. |
| `frontend/scripts/`, `backend/tools/` | Script dev: kiểm tra UI HTTP, đăng nhập E2E, tiện ích tạo key cho môi trường mới; `check_repository_safety.py` và `test_repository_safety.py` kiểm tra source/index Git, không đọc file private. Không chạy tiện ích tạo key để sửa môi trường có dữ liệu. |
| [.github/workflows/verify.yml](.github/workflows/verify.yml) | Safety; frontend lint/types/Node/build; backend Python 3.12.10/pip check/guards/system/migrations/full PostgreSQL + enabled-fixture regression. PG service riêng, không serving/storage secrets; action pins và token chỉ đọc. P1 remote đã PASS trên đúng SHA ghi trong báo cáo P1; mỗi thay đổi P2 cần kết quả trên SHA riêng, không kế thừa CI cũ. Không deploy/live provider acceptance. |
| [.agents/skills/](.agents/skills/) | Project skills được khám phá từ repo: [API review](.agents/skills/bluedrive-api-review/SKILL.md) cho auth/isolation/quota/race; [storage validation](.agents/skills/bluedrive-storage-validation/SKILL.md) cho chọn và đọc bằng chứng integration. Quy trình chung ở DEVELOPMENT, không nhân bản thành năm skill chung chung. |
| `.venv/`, `frontend/node_modules/`, `.next/`, test reports/auth state, `.task01-runtime/` | Dependencies/cache/output/private runtime. Không liệt kê file sinh tự động trong bản đồ, không coi toàn bộ thư mục này là source/module; không sửa dependency đã cài thay cho source. |

## Tài liệu và quyết định lâu dài

| Khi cần | Đọc nguồn này |
| --- | --- |
| Quy trình, setup và lệnh kiểm tra | [AGENTS.md](AGENTS.md), [README.md](README.md), [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) (chu trình sáu bước, bảng chọn test, safety/CI/skills), [backend/README.md](backend/README.md), [frontend/README.md](frontend/README.md). |
| Kiến trúc đích và backlog refactor | [ADR-0010](docs/ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md), [P0 baseline/P1–P8](docs/REFACTOR_P0_BASELINE_2026-11-16.md): inventory/gaps và acceptance gates ban đầu; [ADR-0012](docs/ADR-0012-organization-managed-identities-and-private-my-drive.md) quyết định identity/context P2 development. P3–P8 vẫn là backlog. |
| Baseline tái lập P1 | [ADR-0011](docs/ADR-0011-isolated-test-baseline-and-local-fonts.md), [P1 report](docs/REFACTOR_P1_BASELINE_2026-11-16.md), [75 failure/error records](docs/REFACTOR_P1_FAILURE_CLASSIFICATION_2026-11-16.csv): Python repair, test settings/CI/security/index và Poppins local. P1 accepted development là nền cho P2, không phải nghiệm thu storage/production. |
| Upload, encryption và download | [ADR-0001 lịch sử](docs/ADR-0001-saas-file-transfer-and-encryption.md), [presigned download](docs/PRESIGNED_DOWNLOAD_2026-11-07.md), [adapter guide lịch sử](docs/MINIO_STORAGE_ADAPTER.md). ADR-0010 xác định đích mới. [Thiết kế bảo mật P6](docs/REFACTOR_P6_SECURITY_DESIGN_2026-11-19.md) ở trạng thái PROPOSED. Reader legacy và source hiện tại vẫn cần đối chiếu cho từng luồng. |
| Inventory ownership, revision/routing, topology, monitoring | [ADR-0002](docs/ADR-0002-storage-inventory-ownership.md), [ADR-0003](docs/ADR-0003-immutable-storage-connections.md), [ADR-0004](docs/ADR-0004-topology-layout-preferences.md), [ADR-0005](docs/ADR-0005-scoped-storage-monitoring.md); đi kèm [S2 runbook](docs/STORAGE_CONTROL_CENTER_S2_RUNBOOK.md), [S4 runbook](docs/STORAGE_CONTROL_CENTER_S4_RUNBOOK.md). |
| Chính sách dung lượng/Workspace | [storage plan management](docs/STORAGE_PLAN_MANAGEMENT_2026-11-08.md), [workspace upload quota](docs/WORKSPACE_UPLOAD_QUOTA_2026-11-07.md), rồi đối chiếu `accounts/models.py`, `files/quota.py` và tests. |
| Hệ thống ngữ cảnh và nơi ghi quyết định | [ADR-0006](docs/ADR-0006-project-context-and-development-guidance.md). Ghi ADR nối tiếp trong `docs/`, không tạo thêm kho quyết định ở `docs/context/`. |
| API/schema đề xuất và baseline cũ | [API_CONTRACT_V1.md](docs/API_CONTRACT_V1.md), [DATA_MODEL_MVP.md](docs/DATA_MODEL_MVP.md). Có phần historical/proposed; routes, models, migrations và tests là điểm xác minh implementation. |
| SeaweedFS development và lịch sử | [Platform runbook](infra/seaweedfs/README.md), [Enterprise Lab](infra/enterprise-lab/README.md); [PostgreSQL Platform](docs/PLATFORM_FILER_POSTGRES_2026-11-12.md), [ADR-0007](docs/ADR-0007-platform-filer-postgres-container.md) giữ bằng chứng bootstrap. [ADR-0008](docs/ADR-0008-platform-storage-copy-and-publication.md), [review cutover](docs/PLATFORM_CUTOVER_REVIEW_2026-11-12.md), [Task 01](docs/BLUEDRIVE_BAN_GIAO_TASK01.md) và runtime/evidence cũ là lịch sử có ngày, không là lệnh triển khai P1–P8. |
| Roadmap Storage Control Center | [roadmap index](docs/roadmaps/storage-control-center-2026-11-08/README.md) và các báo cáo `docs/STORAGE_CONTROL_CENTER_S*.md`. Roadmap/S0 cũ không thay trạng thái source S1–S4 hoặc tự phê duyệt gate vận hành. |
| UI và audit đã thực hiện | [UI_REFINEMENT.md](docs/UI_REFINEMENT.md), [UI fixes](docs/UI_FIXES_2026-11-07.md), các báo cáo `SYSTEM_REVIEW_*`/`AUDIT_*` và `.impeccable/` là bằng chứng theo ngày; token/primitives hiện tại là nguồn triển khai UI. |

## Giới hạn xác minh và cách tiếp tục

Checkpoint trước qualification: [Platform 13/11/2026](docs/PLATFORM_CUTOVER_CHECKPOINT_2026-11-13.md); kết quả triển khai/gate tiếp nối ở [qualification runtime](docs/PLATFORM_QUALIFICATION_2026-11-13.md). Phân biệt revision đã read-check với ready đầy đủ; manifest plan-only không cho phép copy/publication/routing. Báo cáo trước giữ bằng chứng test/backup theo ngày.

- Bản đồ xác minh cấu trúc, manifest/lockfile và các entry point local; không chứng nhận phiên bản, cấu hình hoặc sức khỏe production. Khi cần phiên bản framework, ưu tiên manifest/lockfile thay vì liên kết phiên bản trong comment tự sinh cũ ở ASGI/WSGI.
- P0 đã đọc application DB local bằng aggregate an toàn và dùng Docker CLI tại đường dẫn fallback trong handoff để kiểm kê chỉ đọc: Platform 8 container running/healthy với 4 Volume servers (Compose nguồn có 3), Filer PostgreSQL 17.11; Enterprise 5 container Exited. Image digest/mount/network/resource snapshot trong baseline P0. Chưa nghiệm thu S3/browser/worker/restore; số liệu handoff cũ không là kết quả mới.
- **Task 1 project context**, **SeaweedFS Task 01**, và **refactor P0** là phạm vi khác nhau. Hoàn tất tài liệu hoặc test DB không chứng nhận storage/Enterprise/CSE hoặc cấp quyền thao tác runtime. MinIO/cutover đã bị loại khỏi lộ trình đích, dữ liệu runtime hiện tại vẫn được bảo vệ.
- Không cần đọc secret hoặc kết nối database để hoàn thiện bản đồ. Các giá trị cấu hình private không thuộc ngữ cảnh được lưu trong Git; hỏi operator khi tác vụ thật cần thông tin không thể xác minh từ source an toàn.

## Chọn chỗ đặt file và cập nhật bản đồ

1. Tìm giải pháp tương tự trước; sửa/mở rộng module sở hữu hiện tại. Route frontend vào `app/`, UI theo nhóm `components/`, API/policy/helper vào `lib/`; hook gắn một feature đặt cạnh component/hook hiện có.
2. API Django nối qua `urls.py` đúng app, tái sử dụng access/service; model/migration theo app sở hữu dữ liệu. Không tạo app hoặc tầng service mới chỉ vì một endpoint cần thêm logic nhỏ.
3. Test đặt theo convention cùng phạm vi đã có; infrastructure và script provider đặt trong `infra/seaweedfs/` khi phục vụ SeaweedFS. Không tạo một thư mục scripts tổng quát thứ hai nếu đã có nơi phù hợp.
4. Nội quy ở `AGENTS.md`, đường đi ở `MAP.md`, setup/lệnh trong README hoặc `docs/DEVELOPMENT.md`, quyết định lâu dài ở ADR, vận hành ở runbook, kết quả có ngày ở report/evidence. Chỉ tạo tài liệu mới khi không có nơi phù hợp; liên kết thay cho chép nội dung.
5. Cập nhật bản đồ cùng nhiệm vụ khi thêm/xóa/đổi tên/di chuyển module quan trọng hoặc đổi điểm vào/trách nhiệm. Không thêm mọi file test, migration, cache hoặc output sinh tự động vào bản đồ.

## Platform Docker monitoring (2026-11-13)

- `infra/seaweedfs/collect-platform-metrics.py`: host-side read-only Docker sampling, emits a sanitized atomic snapshot in ignored `.local/platform-metrics.json`; `PLATFORM_MONITORING.md` explains operations.
- `backend/infrastructure/platform_live.py`: validates sample age/schema and combines resource telemetry, collection inventory, and instantaneous alerts with the existing SeaweedFS Master topology.
- `frontend/components/storage/PlatformClusterDashboard.tsx`: renders monitoring, real node details, alerts and collection inventory inside the interactive Packet Tracer-style console.
