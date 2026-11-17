# BlueDrive development workflow

**Scope:** development and validation of the current Django + Next.js repository. This document is not a production runbook or a backup/restore procedure.

**Kiến trúc đích từ 16/11/2026:** [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md) chọn SeaweedFS-only, Platform/Enterprise storage độc lập, Enterprise My Drive và CSE có recovery. [P0 baseline](REFACTOR_P0_BASELINE_2026-11-16.md) tách implementation hiện tại, bằng chứng test và backlog P1–P8. Không tiếp tục lộ trình cutover MinIO cũ; không tự thay runtime/data để đồng bộ tài liệu.

## 1. Source-of-truth and local state

Start every task by reading [root AGENTS.md](../AGENTS.md), the relevant sections of [MAP.md](../MAP.md), and the affected directory's instructions. `AGENTS.md` owns project rules; this guide owns setup and validation commands. Keep long-lived decisions in the existing `docs/ADR-*` series, following [ADR-0006](ADR-0006-project-context-and-development-guidance.md); do not create a parallel context/decision archive.

The repository contains application source, database migrations and scripts; **local runtime data is not disposable source code**. PostgreSQL application metadata, separate Filer metadata, object volumes, `backend/media/` encrypted files and referenced keys/configuration must be backed up consistently before approved operations. MinIO is outside the target architecture; that does not authorize deleting any current runtime data. A Git commit or Django migration does not back up stored user files.

The only project Python environment is the **repository-root `.venv/`**. Do not create or select `backend/venv` in VS Code. `.vscode/settings.json` may point to `${workspaceFolder}/.venv/Scripts/python.exe`.

P1: [infra/bootstrap-python.ps1](../infra/bootstrap-python.ps1) tải CPython NuGet **3.12.10** với SHA-256 cố định vào `.python/` ignored rồi tạo/sửa chính `.venv` tại chỗ. `.python` là base runtime, không là venv thứ hai; không đổi Python hệ thống, PATH hoặc registry. Giữ site-packages khi sửa launcher/config. Bản config cũ được giữ tại `.python/pyvenv.before-repair.cfg`; không xóa môi trường để chữa lỗi. Xem [ADR-0011](ADR-0011-isolated-test-baseline-and-local-fonts.md).

Example Windows PowerShell session, from repository root:

```powershell
cd C:\Users\dang2\Project\SecureDrive
.\infra\bootstrap-python.ps1 -InstallDependencies
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe .\backend\manage.py check --settings securedrive.test_settings
```

The path above matches the current workstation; adapt it on other machines.

## 2. Local environment configuration

- Serving Django reads `backend/.env`; Next.js reads `frontend/.env.local`. Default test runner uses `securedrive.test_settings` and does not load either private file.
- Both are ignored by Git. Example files are committed solely as templates with **empty placeholders** or non-secret local origins.
- The Django API typically runs at `http://127.0.0.1:8000`; Next.js at `http://127.0.0.1:3000`.
- Set `NEXT_PUBLIC_API_BASE_URL` to the Django origin, not the object-storage endpoint.
- Keep `NEXTJS_FRONTEND_URL`, `CORS_ALLOWED_ORIGINS`, and `CSRF_TRUSTED_ORIGINS` aligned with the actual browser origin.
- Enable SeaweedFS multipart upload only when the private bucket, approved connection/binding, credentials, TLS policy and browser CORS are configured and qualified. Do not change existing pinned endpoints as a setup shortcut.
- Keep the existing `SECUREDRIVE_AES_KEY` for any existing encrypted files. Replacing it without rewrapping keys can make them unreadable.

**Storage caution:** `docs/MINIO_STORAGE_ADAPTER.md` and the MinIO cutover sections of earlier runbooks are historical; some referenced commands/config files no longer exist in the P0 working tree. Use the SeaweedFS/Enterprise runbooks for source configuration and P0 for current gaps. **Never run `docker compose down -v`, delete volumes, or remove a bind mount as a cleanup step.** Validate instructions against the actual deployment before approved operations.

**P2 Organization accounts (development):** xem [ADR-0012](ADR-0012-organization-managed-identities-and-private-my-drive.md) và [API contract](API_CONTRACT_V1.md#p2-organization-provisioning--2026-11-17). Không convert account hiện hữu hoặc chạy migration P2 trên database phục vụ nếu chưa được phê duyệt. Provisioning mới yêu cầu invitation/email gate hiện có và finite Tenant/Member quotas; không bật flag, đổi email credentials hoặc tự bind Enterprise storage để chữa lỗi test. Các test `accounts.test_organization_identity` và `accounts.test_organization_provisioning` dùng PostgreSQL test riêng, locmem email và account fixture. Shared context/quota changes yêu cầu full regression; UI mocked E2E không chứng nhận invitation delivery hoặc provider thật.

## 3. Start the application

Run these from separate PowerShell terminals. Use the repository-root `.venv` for Django and local npm for Next.js.

```powershell
# Django API, from repository root
.\.venv\Scripts\python.exe .\backend\manage.py runserver
```

```powershell
# Next.js
cd frontend
npm run dev
```

```powershell
# Trusted upload finalization worker, from repository root
.\.venv\Scripts\python.exe .\backend\manage.py run_upload_finalizer
```

The worker is required to publish completed multipart uploads in local development. In deployment the equivalent job must be supervised and monitored. `cleanup_uploads` is a state-changing maintenance command: schedule it under a deliberate operations policy, not as a casual diagnostic command.

## 4. Verify changes

For **documentation-only** changes:

```powershell
git status --short
git --no-pager diff --check
git --no-pager diff --stat
```

For **code or dependency** changes, run the relevant suites; for full regression:

```powershell
# Backend: từ repository root, dùng PostgreSQL test DB riêng mới
.\.venv\Scripts\python.exe .\backend\manage.py check --settings securedrive.test_settings
.\.venv\Scripts\python.exe .\backend\manage.py makemigrations --check --dry-run --settings securedrive.test_settings
.\.venv\Scripts\python.exe .\infra\seaweedfs\regression.py
# Truyền Django test label vào regression.py để chạy phần liên quan.

# Frontend
cd frontend
npx tsc --noEmit
npm run lint
npm run build
```

Run feature unit-test scripts defined in `frontend/package.json` as appropriate. For all current Node unit tests, run `rg --files components lib -g '*.test.mts'` from `frontend/` and pass the resulting paths to `node --experimental-transform-types --test`. Browser suites and their data-writing scope are documented in [frontend/e2e/README.md](../frontend/e2e/README.md). A documentation-only task does not require application/runtime tests; validate links, consistency and the changed text instead. Historical test counts are not a current test result.

**PostgreSQL test database:** Running two Django test suites at the same time can leave a session connected to the same `test_*` database and prevent teardown/recreation. Only run one full test suite per test database at a time. Do not terminate another legitimate test's DB session or delete the application's real database.

`infra/seaweedfs/regression.py` chooses a previously absent random test DB and accepts Django test labels. It forces isolated test settings by default and rejects `--keepdb` and zero discovery. Serving `DB_*`, dotenv, feature flags and `DJANGO_SETTINGS_MODULE` cannot silently select the default test context. Provider suites stay skipped unless the explicit live mode is authorized; skip does not certify integration. Test settings use the existing HTTP development policy; production TLS/cookie/auth guards remain unchanged.

### 4.1 PostgreSQL test riêng

Yêu cầu Docker/Compose, `.venv` đã bootstrap và port loopback 55432 còn trống. [infra/postgres-test.compose.yml](../infra/postgres-test.compose.yml) chỉ tạo project `bluedrive-tests`, PostgreSQL **18.6** ghim digest, data trên tmpfs; không mount hoặc kết nối data/volume Django/Filer. Không cần serving `.env`, account hay SeaweedFS để chạy default regression.

Từ root, trong cùng PowerShell process, cấp password test ngẫu nhiên không in ra terminal:

```powershell
$testPasswordBytes = New-Object byte[] 32
$testRandom = [System.Security.Cryptography.RandomNumberGenerator]::Create()
$testRandom.GetBytes($testPasswordBytes)
$testRandom.Dispose()
$env:BLUEDRIVE_TEST_DB_PASSWORD = [Convert]::ToBase64String($testPasswordBytes)
docker compose -f infra/postgres-test.compose.yml up -d --wait
.\.venv\Scripts\python.exe -X utf8 backend/manage.py check --settings securedrive.test_settings
.\.venv\Scripts\python.exe -X utf8 backend/manage.py makemigrations --check --dry-run --settings securedrive.test_settings
.\.venv\Scripts\python.exe -X utf8 infra/seaweedfs/regression.py
# Khi đã xong test, chỉ dừng project test của phiên này; không down -v.
docker compose -f infra/postgres-test.compose.yml stop postgres
```

Không sinh lại password cho container test đang chạy; nó phải khớp password đã cấp lúc bootstrap DB. Nếu dùng nơi lưu password test private, chỉ nạp vào process và không commit/in giá trị. CLI Docker không trong PATH có thể dùng đường dẫn đã xác minh trong handoff; không cài/đổi Docker hoặc restart storage để chạy test.

Contract P1.1: profile `BLUEDRIVE_TEST_DB_TARGET=local` (mặc định) chỉ chấp nhận `127.0.0.1:55432`; profile `ci` chỉ chấp nhận `127.0.0.1:5432`. Cả hai cố định `NAME=bluedrive_test_control`, `USER=bluedrive_test`; `PASSWORD` cần cấp riêng. Các override HOST/PORT/NAME/USER chỉ hợp lệ nếu khớp hoàn toàn profile, không chấp nhận hostname, DSN, port/role/control DB tùy ý. Muốn thêm target phải review source contract trước.

Compose mount read-only [init SQL](../infra/postgres-test-init.sql) để đặt marker trên control DB test tmpfs; CI đặt cùng marker sau khi cài psycopg. Runner kiểm tên/host/port/role/options và đọc lại identity/marker server trước tạo và trước hủy DB UUID. Thiếu marker hoặc cấu hình lệch thì dừng; không tự sửa marker, drop DB hoặc kết nối serving/Filer để chữa lỗi. Không migrate control DB. Khi chuyển từ test container P1 cũ chưa có init mount, chỉ recreate service test theo Compose này; không dùng `down -v`.

Test settings giữ allowlist environment suốt process, không trả credential runtime về sau import. dotenv luôn disabled; libpq hostaddr/passfile và AWS credential files/metadata được khóa về test/disabled. Các service đọc `os.environ` chỉ nhận credential được fixture cấp trong scope; không đưa credential runtime vào các biến OS được giữ lại. Shell cha không bị sửa vì mỗi lệnh Python là process riêng. Phải bắt đầu process mới trước khi runtime settings được import; guard từ chối module cache runtime đã nạp. Dùng runner bên trên: `manage.py test --settings securedrive.test_settings` bị chặn trước tạo DB để tránh đi vòng UUID/marker guards.

Test defaults: các rollout flags OFF, profile registry rỗng, storage endpoint `.invalid`, email locmem và media tạm. Enabled tests dùng `override_settings`, ready connection/binding và FakeS3 có scope. CI chạy thêm suite riêng:

```powershell
.\.venv\Scripts\python.exe -X utf8 infra/seaweedfs/regression.py infrastructure.test_storage_routing infrastructure.test_runtime_qualification infrastructure.test_telemetry infrastructure.test_layouts files.tests.test_presigned_download
```

Không chạy flag ON trên fixture unpinned rồi hạ assertion. Khi thực sự nghiệm thu provider theo runbook đã duyệt, dùng `regression.py --live-storage --confirm-live-storage <approved-fixture-scope> <labels>` với `SEAWEEDFS_INTEGRATION=1`, `SEAWEEDFS_ALLOW_TEST_WRITES=1`; CI chặn mode này. Chỉ nhận hai module alias `files.tests.test_seaweedfs_integration`, `files.tests.test_seaweedfs_finalizer_integration` hoặc class tương ứng `SeaweedFSIntegrationTests`, `SeaweedFSFinalizerIntegrationTests` có đầy đủ module prefix. Alias được đổi thành đúng provider class, không khám phá toàn module; labels app, method, path, wildcard, MinIO hoặc nhãn khác đều bị chặn trước setup/ghi tài nguyên, kể cả khi trộn nhãn hợp lệ.

Live vẫn dùng `securedrive.test_settings`: DB UUID/marker guards, MEDIA_ROOT tạm, email locmem, key test và registry/endpoint ứng dụng cô lập. Không đọc `.env` runtime. Chỉ cấp lại `SEAWEED_S3_{ENDPOINT,PUBLIC_ENDPOINT,BUCKET,ACCESS_KEY,SECRET_KEY}`, hai gate integration/write và `FRONTEND_ORIGINS` đã duyệt. Scope là định danh chữ thường/số/gạch ngang 1–32 ký tự; bucket phải đúng `bluedrive-test-<scope>` và đã được operator chuẩn bị riêng, không được dùng bucket phục vụ. Endpoint nội bộ chỉ `http://127.0.0.1:<port>`, public chỉ IP đó hoặc `http://s3.localhost:<port>`; không userinfo/path/query/fragment/whitespace. HTTP gate ghim `s3.localhost` về TCP loopback, không sửa host đã ký. Origins CORS chỉ localhost/127.0.0.1 port 3000, đây là header kiểm tra chứ không phải đích gọi frontend.

Credential phải có cả access/secret và chỉ có quyền bucket fixture/object operations theo runbook; không lấy fallback credentials, không nâng grant hoặc bootstrap bucket bằng harness. Provider tests vẫn giữ assertion deny anonymous/sai credential/cross-bucket/bucket administration, integrity/quota và cleanup đúng key ngẫu nhiên. Xác nhận CLI không thay phê duyệt vận hành. Không chạy live mode như một phần P1/P1.1, không dùng account/data thật để test phá hủy. Namespace và loopback là guard chống chọn nhầm, không thay bucket ownership/credential policy được operator kiểm chứng.

## 5. Git and cleanup discipline

The current target follows [ADR-0010](ADR-0010-seaweedfs-enterprise-and-client-encryption-target.md). The MinIO copy/cutover plan in [ADR-0008](ADR-0008-platform-storage-copy-and-publication.md) is historical and its commands are absent in the P0 working tree. Do not execute or restore that workflow as part of P0–P8. Keep referenced revisions/readers/keys for existing runtime data; changes to endpoints, flags or data require explicit scope and backup/restore evidence. Do not reset file data or weaken tests to complete a provider change.

1. Check `git status --short`, inspect existing diffs/untracked files and record the initial state. If the tree is already dirty, preserve that work and keep your change scoped; do not force a clean tree with reset, checkout, stash or broad staging.
2. Review a narrow change set. Do not mix documentation and security/behavior refactoring in one commit.
3. Back up any replaced files to **Windows Downloads** before applying automated cleanup scripts. Never store clean-up exports inside the repository.
4. Avoid broad deletions. In particular, **never delete** migrations, `.enc` media, PostgreSQL data, MinIO objects/volumes, or cryptographic keys based on static import results.
5. Run checks; use `git --no-pager diff --check` and `git --no-pager diff --cached --stat` to avoid the interactive `less` pager.
6. Commit only inspected, related paths; do not use `git add .` when unreviewed files exist.

Historical Phase 2.1 cleanup removed 17 hash-verified unused files in commit `f932b95` after 349 Django tests and frontend checks passed. The change was backed up separately in Downloads.

## 6. Documentation update policy

- Root `README.md`: project overview and validated quick start.
- `backend/README.md`: backend setup, configuration, workers and tests.
- `frontend/README.md`: frontend setup, environment, test scripts and API boundary.
- `docs/`: architecture decisions, proposed API contracts, implementation-specific guides, and this workflow.
- Root `AGENTS.md`: development/security rules and approval boundaries. Root `MAP.md`: source responsibilities, entry points and documentation navigation; update it in the same task when an important module is added, removed, renamed or moved.
- `docs/ADR-NNNN-*.md`: the existing single location for durable decisions, including business/security constraints, alternatives and consequences. Update the relevant guide instead of creating another document with the same purpose.
- Where older documents describe proposals or past baselines, label them **historical/proposed** rather than implying the feature is currently deployed.

All nontrivial refactors must preserve tests and authorization invariants. A front-end component with no static import may still be an App Router page, dynamically imported component, or server-discovered module; inspect runtime references before removal.

## 7. Engineering harness

Áp dụng **UNDERSTAND → PLAN → IMPLEMENT → TEST → REVIEW → REPORT**. Mục tiêu là một chu trình ngắn có bằng chứng, như kiểm bản vẽ, thi công rồi kiểm định trước khi bàn giao; không thêm tầng quản lý dự án riêng.

| Bước | Việc cần hoàn tất |
| --- | --- |
| UNDERSTAND | Đọc AGENTS/MAP, code/callers/test và ADR liên quan; xác định luồng dữ liệu, quyền, quota, compatibility và phạm vi ảnh hưởng; ghi nhận Git dirty ban đầu. |
| PLAN | Nêu vấn đề thực sự, so sánh sửa tối thiểu với refactor, chọn thay đổi nhỏ có cách kiểm chứng; xin duyệt thay đổi kiến trúc ngoài phạm vi. Nhiệm vụ nhỏ dùng kế hoạch trong phần trao đổi; nhiệm vụ lớn ưu tiên roadmap/ADR hiện có, chỉ thêm SPEC/PLAN khi thật cần. |
| IMPLEMENT | Sửa đúng phạm vi, tái sử dụng service/hook/component; giữ compatibility đến khi có migration được duyệt; không thay dữ liệu đang dùng hoặc thêm abstraction/dependency theo thói quen. Với yêu cầu chỉ test/review, chỉ triển khai fixture/correction đã được yêu cầu. |
| TEST | Chạy kiểm tra theo bảng dưới, regression cho luồng dùng chung và lint/typecheck khi phù hợp. Giữ assertion/bảo vệ; lỗi môi trường không được biến thành bỏ kiểm tra. |
| REVIEW | Đọc lại diff và các đường lỗi: auth/CSRF/tenant/Workspace; quota/integrity/DB constraint; race/lock/retry/idempotency/cleanup; pagination/N+1/memory/timeouts. Với UI, so token/primitives/theme và keyboard/focus/responsive. Với migration, giải thích dữ liệu bị ảnh hưởng và phương án phục hồi/forward-fix. |
| REPORT | Tóm tắt hành vi thay đổi, file sửa, lệnh/test count và PASS/FAIL/SKIP/BLOCKED; nêu giới hạn, rủi ro và bước phụ thuộc tiếp theo. Không coi code xong, 0 test, mock pass hoặc skip provider là nghiệm thu. |

`PASS`: đã chạy và đạt trong phạm vi ghi rõ. `FAIL`: đã chạy và vi phạm kỳ vọng. `SKIP`: chủ động không chạy vì ngoài phạm vi/không áp dụng, có lý do. `BLOCKED`: kiểm tra cần thiết chưa chạy/hoàn tất vì thiếu môi trường, thông tin hoặc quyền; nêu cách gỡ chặn. Không đánh PASS tổng thể nếu gate bắt buộc còn FAIL/BLOCKED. Không cần tạo file báo cáo cho từng thay đổi nhỏ; báo trong kết quả nhiệm vụ, chỉ lưu evidence khi phục vụ nghiệm thu thực sự.

### Chọn kiểm tra theo phạm vi

| Thay đổi | Kiểm tra phù hợp |
| --- | --- |
| Tài liệu/skill | Link/path/frontmatter, quy tắc xung đột, whitespace và diff; không chạy app suite chỉ vì đổi câu chữ. |
| Tool kiểm tra repository/CI | Unit tests của tool, safety scan working tree + index, validate YAML/command và chạy các command độc lập khả dụng; chưa chạy trên GitHub phải nói rõ. |
| API/model/service | Django check, migration check và test label qua runner DB riêng; test âm về quyền/scope/error. Model/transaction/luồng dùng chung cần regression các app liên quan hoặc full backend. Không dùng data DB thực để test migration. |
| Frontend UI/service/hook | Node test liên quan, lint, `next typegen` rồi `tsc --noEmit`; build nếu ảnh hưởng runtime/build/dependency. Mocked browser tests cho tương tác; live tests cần test account và phạm vi ghi fixture đã duyệt. |
| Quyền/quota/race | Bổ sung tình huống chéo tenant/Workspace, thu hồi quyền, request đồng thời, retry/abort/stale worker theo rủi ro; chạy regression quota/sharing/finalization hoặc infrastructure tương ứng. |
| Storage | Adapter/factory regression + config unit test; khi thay contract/provider phải kiểm nghiệm thật multipart/checksum/presign/resume/CORS/version/worker/persistence theo runbook. Không tự chuyển endpoint hoặc reset dữ liệu để test. |

Lệnh portable cho bộ kiểm tra repository, từ root với Python 3.12 đang dùng:

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s .\backend\tools -p test_repository_safety.py -v
.\.venv\Scripts\python.exe -X utf8 .\backend\tools\check_repository_safety.py
.\.venv\Scripts\python.exe -X utf8 .\backend\tools\check_repository_safety.py --staged
```

Với frontend checkout mới, từ `frontend/` chạy `npx.cmd --no-install next typegen` trước `npx.cmd --no-install tsc --noEmit`; route types/`next-env.d.ts` được Next.js sinh mà không cần build tải font. Chỉ dùng package đã cài đúng lock; không cho `npx` tải package khác để chữa lỗi command. Không sửa source trong `node_modules`.

### CI và giới hạn

[GitHub Actions verify](../.github/workflows/verify.yml) có ba job: repository safety/self-tests; frontend `npm ci --ignore-scripts`, lint/typegen/typecheck/Node tests/**production build với Poppins local**; backend CPython 3.12.10, pinned requirements/`pip check`, guard tests, system/migration checks và full PostgreSQL regression cùng enabled-fixture suite. PostgreSQL test service 18.6 được ghim digest, loopback, control DB/role riêng; password theo run ID/attempt chỉ dùng trong runner tạm, không là credential runtime. Không có provider credential, Django serving DB, E2E login, deploy hoặc auto-cutover. Cả runner backend và Node discovery đều từ chối 0 bài. Actions ghim commit; token `contents: read`, checkout không giữ credential. Không dùng `pull_request_target` để chạy code PR.

CI này chưa bao gồm browser E2E, storage/worker/restore thật hoặc benchmark tải. Các gate đó vẫn cần môi trường/fixture được duyệt; CI xanh không thay chúng. Workflow chỉ được xuất bản/chạy trên GitHub khi người dùng commit/push; validate YAML và chạy command tương đương local không chứng minh đã chạy remote. Khi working tree có nhiều thay đổi untracked từ trước, phải review đầy đủ baseline phụ thuộc trước khi chuẩn bị PR; không stage toàn bộ tự động.

## 8. Secrets và dữ liệu trong repository

- Chỉ kiểm kê tên/trạng thái ignore/tracking của `.env`, private config, auth state, backup/dump; không mở hoặc sao chép giá trị khi không cần. `.env.example` giữ biến cấu hình và default không nhạy cảm; trường credential phải rỗng hoặc placeholder rõ. Không đổi credential/ACL/database grant trong công việc harness.
- `.gitignore` ngăn thêm env, SeaweedFS `.local`, E2E auth state, khóa private và tên backup/dump phổ biến. Ignore không gỡ file đã tracked; safety guard báo FAIL nếu artifact private nằm trong source/index, kể cả force-add. Không tự xóa/untrack/rewrite history khi phát hiện; báo vị trí đã che giá trị và xin phạm vi xử lý phù hợp.
- Guard kiểm tra các dạng token/private key/URL ký/DSN chứa password đã biết và literal credential trong config/source thông thường. Nó chỉ in đường dẫn/dòng/loại, không in giá trị; kiểm tra index riêng để phát hiện secret đã stage dù working tree đã sửa. File private bị chặn theo tên trước khi đọc, link/unreadable là BLOCKED. `.env` ignored không được đọc.
- Đây là guard nhỏ theo pattern, không chứng nhận mọi secret đều vắng mặt: mặc định không quét history; `--history [REF]` là opt-in đọc source reachable local và vẫn chặn blob có alias private trước khi mở. Không quét dữ liệu nén/binary tùy ý hoặc mọi hình thức che giấu credential. Binary không quét được báo số lượng; generic literal trong fixture test được bỏ qua, nhưng token/key/URL theo pattern vẫn quét, ngoại trừ bốn sentinel password giả trong URL của test (`password`, `secret`, `test`, `dummy`). Sentinel này không được miễn trừ trong runtime source/config. Nếu nghi lộ credential thật, cần quy trình điều tra/rotation riêng đã duyệt; không in nó để chứng minh.
- Scan working tree và index độc lập: source đã sửa chưa stage có thể PASS trong working tree nhưng FAIL trong index cũ. Đối chiếu đường dẫn/loại phát hiện và phần thay đổi đã che giá trị; không tự stage/reset index của người dùng để lấy kết quả PASS. Chạy lại `--staged` sau khi người dùng đưa đúng thay đổi đã review vào commit.
- Mẫu bảo vệ backup theo đuôi/tên phổ biến, không ignore toàn bộ `*.sql` vì SQL source/migration có thể hợp lệ; guard nhận biết header PostgreSQL/MySQL dump và magic custom dump. Không lẫn trang UI `admin/backups/` với nơi lưu backup dữ liệu.
- Lệnh `seed_demo` không còn password mặc định và không in password; operator phải cấp `BLUEDRIVE_DEMO_PASSWORD` qua process env khi chủ động seed môi trường demo riêng. Giữ tùy chọn `--password` để tương thích lời gọi cũ nhưng không khuyến nghị truyền secret trên command line. Thiếu password dừng trước clear/create; harness không chạy seed hoặc đổi mật khẩu tài khoản đã tồn tại. Các tài khoản demo đã tạo trước đây cần đánh giá riêng nếu từng dùng default cũ, không suy rằng sửa source đã đổi credential đang hoạt động.

## 9. Project skills

| Skill | Vì sao cần / khi dùng |
| --- | --- |
| [bluedrive-api-review](../.agents/skills/bluedrive-api-review/SKILL.md) | Gom quy trình trace API qua auth/isolation/quota/revision/worker/race, vì một checklist ngắn dễ bỏ sót tương tác giữa các tầng. Dùng cho API/security review hoặc thay đổi chạm các ranh giới này. |
| [bluedrive-storage-validation](../.agents/skills/bluedrive-storage-validation/SKILL.md) | Giúp chọn gate và đọc đúng bằng chứng provider/browser/worker, vì unit xanh hoặc metadata nội bộ không chứng minh dữ liệu người dùng an toàn. Dùng cho nghiệm thu storage/thay contract, không tự cấp quyền cutover. |

Hai skill đặt tại `.agents/skills/`, mỗi skill chỉ có `SKILL.md`, có mục tiêu, phạm vi, workflow, completion/report và liên kết nguồn. Không tạo skill regression mới vì runner và bảng chọn test đã đủ; review UI dùng design system hiện có và quy trình REVIEW, không tạo một bản sao hướng dẫn UI. Các dự án/công cụ ngoài như Graphify vẫn tùy nhu cầu, không là dependency để harness hoạt động.

Nguồn đối chiếu cấu hình CI: [GitHub token permissions](https://docs.github.com/en/actions/tutorials/authenticate-with-github_token), các release chính thức [checkout](https://github.com/actions/checkout/releases/tag/v7.0.1), [setup-python](https://github.com/actions/setup-python/releases/tag/v7.1.0), [setup-node](https://github.com/actions/setup-node/releases/tag/v7.1.0). Typegen đối chiếu tài liệu Next.js đã cài và [CLI chính thức](https://nextjs.org/docs/app/api-reference/cli/next#next-typegen-options).
