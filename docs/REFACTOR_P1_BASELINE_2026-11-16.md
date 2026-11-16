# BlueDrive — P1: Reproducible Baseline, Security & CI

Ngày: **16/11/2026**, Asia/Bangkok. Phạm vi: F10/F14/F15/F16/F18 của [P0](REFACTOR_P0_BASELINE_2026-11-16.md). Quyết định dài hạn ở [ADR-0011](ADR-0011-isolated-test-baseline-and-local-fonts.md). **Đã triển khai P1 và kiểm tra local; không triển khai P2–P8, không commit/push/deploy. GitHub Actions remote chưa chạy.**

## 1. Kết quả và ranh giới

- Full Django/PostgreSQL: **614 discovered/run, 595 thực thi, 19 skipped, 0 failures, 0 errors**, 979.030s; test DB riêng đã teardown. Không tính 19 provider tests skipped là PASS.
- Suite feature-enabled: **72/72 PASS, không skip**, 77.480s; là subsuite đã nằm trong full regression, không cộng thành số bài unique mới. Có binding/connection revision/FakeS3 fixtures và negative scope/CSRF/quota/version cases.
- Guard tests: **19/19 PASS**, 8.305s. Crypto regression riêng: **9/9 PASS**, 0.175s; cũng đã nằm trong full suite.
- Frontend: lint, typegen, TypeScript, **159/159 Node tests** và production build **PASS**. Poppins local giữ family, weights, CSS variable và design tokens.
- Python `.venv` đã chạy lại bằng full CPython 3.12.10 trong dự án; dependency versions đã cài không đổi. Working-tree và index safety được kiểm tra độc lập; index chỉ stage đúng bản sửa bảo mật `seed_demo.py` đã có trước P1.
- Đã tái hiện đúng **55 failures + 20 errors** của P0 trước khi sửa; phân loại đủ **75 records thuộc 61 test methods** tại [CSV đầy đủ](REFACTOR_P1_FAILURE_CLASSIFICATION_2026-11-16.csv).

Không sửa business API/model/migration, Tenant/My Drive/provisioning, permission service, quota, crypto implementation hoặc runtime routing. Không migrate serving DB, xóa Docker volume, chạy cleanup/finalizer/probe trên dữ liệu thật hoặc đổi key/credential runtime. Các lệnh tạo/destroy DB và media fixture chỉ diễn ra trong phạm vi test.

Giống phòng kiểm định có nguồn điện riêng: P1 giữ đúng máy móc và quy trình kiểm quyền, nhưng không để công tắc vận hành của nhà kho thay đổi điều kiện bài thử.

## 2. Trạng thái Git trước P1 và bảo toàn công việc cũ

HEAD trước/sau: `d968ebffa0d17f4fce81c2b2f56af5021e60e070`. Bắt đầu với **270 status entries**, chưa có staged changes; working tree đã chứa code/migration/infra/CI/UI và tài liệu P0 chưa commit. Snapshot hash **642 file nonignored hiện hữu** được dùng để phân biệt delta P1; dữ liệu private và runtime/cache không thuộc snapshot source.

- Các thay đổi có sẵn trước P0 và 19 tài liệu P0 được nhận diện theo báo cáo/manifest P0, không gộp vào thành quả P1. Không reset/stash/checkout hoặc stage toàn bộ để lấy tree sạch.
- Với 15 file hiện hữu được P1 cập nhật, baseline bytes được lưu hoặc tái dựng và **đối chiếu đúng SHA-256 snapshot trước P1**. Patch review dùng baseline working tree đó, không dùng toàn bộ diff với HEAD.
- [Patch riêng P1](REFACTOR_P1_CHANGES_2026-11-16.patch) gồm source/docs/assets của P1; tự nó không chứa thay đổi index-only của `seed_demo.py` vì working file này đã được sửa từ trước P1. Patch không bao gồm chính file patch để tránh tự tham chiếu.
- Cuối nhiệm vụ phải đối chiếu hash các file ngoài phạm vi, HEAD, index paths và `git diff --check`; kết quả review cuối ghi ở §9. Những file untracked thuộc baseline vẫn cần được người dùng review khi chuẩn bị PR; không tự thêm chúng vào index.

## 3. Root cause và cách xử lý

### F15 — Python launcher mất base interpreter

`pyvenv.cfg` trỏ `C:\Users\dang2\AppData\Local\Programs\Python\Python312` không còn dùng được; launcher báo `No Python at ...`. Python `.task01-runtime/python` có version 3.12.10 nhưng là embeddable distribution, thiếu module `venv`, đồng thời dùng site-packages của `.venv` qua `_pth`.

`infra/bootstrap-python.ps1` giải quyết bằng full CPython NuGet **3.12.10**, package SHA-256 `0eb85c2dfccccf1b17352de4c397f69194035b7d37149eacc16f1147d93de3b8`. Package có `venv`/`ensurepip`; executable quan sát có Authenticode **Valid**, publisher **Python Software Foundation**. Base runtime nằm `.python/cpython-3.12.10/tools`; `.venv` vẫn là virtual environment duy nhất. Dùng `venv --upgrade --without-pip` cho venv hiện hữu, giữ site-packages và lưu config cũ; không sửa system Python, PATH hoặc registry.

Bootstrap đã chạy thành công và chạy lại idempotent. `-InstallDependencies` báo requirements đã satisfied; `pip check` PASS. Ghim thêm năm dependency bắc cầu đang cài — jmespath 1.1.0, python-dateutil 2.9.0.post0, s3transfer 0.19.3, six 1.17.0, urllib3 2.8.0 — để fresh install không tự chọn bản khác. Django 5.2.17, DRF 3.18.0, Psycopg 3.3.6 và các package khác giữ nguyên. Không đưa tool local `git-filter-repo` vào dependency ứng dụng.

Script dùng UTF-8 BOM để Windows PowerShell 5.1 đọc đúng tiếng Việt. Lượt thử đầu gặp lỗi parser encoding, đã sửa và thực thi lại script thật; không tính lượt lỗi đó là thành công.

### F16 — Runner tạo DB riêng nhưng kế thừa configuration runtime

Runner cũ load `securedrive.settings`, settings gọi dotenv. Cấu hình P0 có routing và runtime probes ON; nhiều bài mock/legacy không định nghĩa lại rollout flags. Routing guard đúng đã chặn các fixture chưa có pin/binding trước khi tới assertion quota, ownership, download hoặc cleanup mà bài đang muốn kiểm.

`securedrive.test_settings` import cùng application settings trong environment tạm có `PYTHON_DOTENV_DISABLED=1`, secret/key test ngẫu nhiên và `BLUEDRIVE_TEST_DB_*`. Các flags mặc định OFF, profile registry rỗng, endpoint storage `.invalid`, media ở temp directory và email locmem. Đây là contract của test, không đổi flags serving và không bỏ middleware/ACL/quota/constraints. PASSWORD_HASHERS và bốn password validators không bị hạ để tăng tốc.

Reader AES legacy đọc key trực tiếp từ process environment (`backend/security/aes_service.py:14`), thay vì chỉ đọc Django settings. Lượt isolated đầu đã hết toàn bộ 75 lỗi cũ nhưng có ba errors mới: `security.tests.EncryptionServiceTests.test_dek_wrap_unwrap`, `test_wrapped_dek_is_not_plaintext_dek`, `test_wrong_master_key_cannot_unwrap_dek`. Test settings nay cấp **cùng key test ngẫu nhiên** vào env của riêng process; không đổi reader/format/key runtime. Sau sửa, crypto 9/9 và full regression PASS.

Runner mặc định ép test settings, chặn inherited settings selector, zero discovery và keepdb. Live provider cần `--live-storage` cùng gate hiện hữu; CI từ chối mode live trước khi load runtime settings. Guard unit tests dùng inherited sentinel, profile JSON sai, runtime flags ON và DB name ngoài namespace để kiểm fail-closed.

### F10 — Thiếu backend/PostgreSQL CI

Workflow thêm backend job với CPython 3.12.10, PostgreSQL **18.6** service riêng, image digest ghim, loopback port và test DB/role độc lập. Job cài requirements, `pip check`, guard tests, source/index safety, Django check, migration consistency, full regression và enabled-fixture subsuite. Frontend job thêm production build thật.

Không có serving DB/storage credentials, `.env`, S3 service, live opt-in, deploy hoặc schema migration vào serving trong default CI. Password PostgreSQL service là biểu thức theo run ID/attempt của runner tạm; nó không phải runtime secret và không được tái sử dụng cho deployment. Safety guard chỉ nhận biết đúng biểu thức dynamic đó và có negative tests cho literal/arbitrary expression; không miễn trừ mọi workflow hoặc mọi password.

YAML được parse bằng `js-yaml` đã cài; kiểm ba jobs, action SHA pins, read-only permissions và isolated backend settings PASS. Các bước tương đương đã chạy local. **Chưa xuất bản/chạy workflow mới trên GitHub** vì nhiệm vụ cấm commit/push; đây là gate remote còn mở.

### F18 — Working tree sửa đúng nhưng index vẫn giữ literal cũ

Trước P1, index bằng HEAD cho `backend/dashboard/management/commands/seed_demo.py`, scanner báo `credential-literal` ở dòng 25; working tree đã bỏ default password và output password. Diff đã được xem với literal redacted. Mọi hunk của file đều thuộc cùng sửa bảo mật: thêm lấy mật khẩu từ process env, từ chối thiếu password trước clear/create và bỏ in password.

Đã **stage duy nhất file này** theo yêu cầu xử lý index của P1. Working file không bị thay lại, không stage nguồn khác, không commit/push. Index scan PASS; tests seed thiếu password và không in password nằm trong full regression. Hai commit lịch sử có liên quan `9259654be9d2`, `e8979b6b13b6` vẫn chứa finding; chỉ ghi loại/path, không in literal hoặc rewrite history. Không suy rằng tài khoản demo/runtime đã được rotate.

### F14 — Build phụ thuộc tải Google Fonts

`next/font/google` cần tải CSS/font trong bước build; P0 thất bại ở kết nối Google Fonts. Đọc API local của Next.js 16.3.3 rồi dùng `next/font/local` với Poppins original normal 400/500/600/700. Bốn TTF và OFL được lấy từ Google Fonts commit `8b0a1d0f5983c89bc2b93f1b5fb55f9e252744b5`, checksum ở [font README](../frontend/app/fonts/poppins/README.md).

Giữ `--font-poppins`, `display: swap`, theme/tokens/UI và không thêm dependency. Build đã compile, typecheck và tạo đủ **40/40 static pages**, exit 0, không dùng mock font. Full TTF có thêm glyph ngoài Latin và tổng 632.200 bytes; đây là trade-off asset payload, không tuyên bố giảm bundle hoặc pixel-identical visual QA. Browser visual/device QA không chạy trong P1.

## 4. Phân loại đủ 55 failures và 20 errors

[CSV 75 records](REFACTOR_P1_FAILURE_CLASSIFICATION_2026-11-16.csv) có ID P0-01…P0-75, test ID chuẩn hóa sau line wrapping của PowerShell, subtest, observed error, nguyên nhân, source/test path:line, cách xử lý và kết quả sau. Có **61 methods**, do subtests endpoint/resolver/role/metadata tạo nhiều result records. Không gộp chúng thành một lỗi để giảm số đếm.

| Nhóm | Records | Nguyên nhân đã đối chiếu source và kết quả |
| --- | ---: | --- |
| G1 — Session/legacy resolver | 11 errors | Routing ON đòi pin nhưng scenario legacy dùng unpinned session/location; guard `storage_routing.py:52,69`. |
| G2 — Presigned fixture | 19 (16 failures, 3 errors) | Direct-download ON không đồng nghĩa multi-cluster routing ON. Unpinned fixture bị 503 trước mode/version/cookie assertions; KeyError là hậu quả response lỗi. |
| G3 — Global adapter factory | 2 errors | Factory global đúng là bị từ chối khi routing ON; các bài đang kiểm legacy/public signer cần baseline OFF riêng. |
| G4 — Upload/quota/finalizer admission | 32 (29 failures, 3 errors) | Thiếu verified binding dưới inherited routing ON nên dừng trước reserve/quota/worker setup; 503, missing upload_id/failure_code là hậu quả. Không nâng quota hoặc bỏ kiểm binding. |
| G5 — Binary/ZIP/legacy decrypt | 9 (8 failures, 1 error) | Reader S3 unpinned bị chặn nên response là lỗi/redirect, không phải streaming ZIP. Không bỏ hash/decrypt/size checks. |
| G6 — Collaboration duplicate | 1 failure | `dashboard/drive_api.py:264` gọi upload_target trước publication mock; fixture collaboration chưa có binding. Không đổi quy tắc owner/folder để sửa. |
| G7 — Capability defaults | 1 failure | Assert source-default OFF trong khi routing/runtime probes kế thừa ON; P0 đã chứng minh chỉ OFF routing vẫn còn assert runtime probe. Positive ON override vẫn giữ. |
| **Tổng** | **75 = 55 failures + 20 errors** | Full suite sau P1 PASS; tất cả 61 affected methods còn discoverable và không bị skip. |

Phân loại theo yêu cầu:

- **Môi trường/inherited flags:** nguyên nhân chung đã được chứng minh cho các records trên, với từng branch/source và response symptom riêng trong CSV; không mặc định suy luận từ tên test.
- **Fixture/setup:** implicit legacy/default context gây sai scenario khi kế thừa rollout; enabled binding/FakeS3 fixtures đã có hợp lệ và được chạy riêng. Ba errors key AES phát sinh khi cô lập môi trường là thiếu fixture process key, đã sửa trong test settings.
- **Nghiệp vụ thực sự:** không xác minh được một defect độc lập trong 75 records sau khi chạy đúng scenario; không sửa business code để ép xanh. Các gap Enterprise/P0 F17 vẫn nằm ngoài P1.
- **Migration/PostgreSQL constraints:** không có record trong 75 cho thấy migration/constraint bị hỏng; full suite migrate DB test mới trên PostgreSQL 18.6 và các negative constraint/race tests được giữ. Không dùng SQLite hoặc sửa migration/assertion.
- **Dependency/concurrency:** không có bằng chứng chúng là root cause của 75 records; `pip check` PASS. Full suite và enabled suite dùng UUID DB khác nhau khi chạy song song local; CI chạy tuần tự hai bước. Không chia sẻ/reuse test DB hoặc kill session khác.

## 5. Test configuration và flag matrix

| Scenario / flags | Cấu hình và fixture | Bằng chứng |
| --- | --- | --- |
| Baseline legacy/mock | Tất cả rollout flags OFF, registry rỗng, `.invalid` storage, temp media/random keys | Full suite; guard inherited config/invalid profile/DB namespace. |
| Routing ON / không pin | Từ chối upload/location/global fallback kể cả cleanup | `StrictRoutingGuardsTests`; không đổi assertion. |
| Routing ON / có pin | Ready revision/binding, FakeS3 theo connection; thiếu hoặc sai ownership/binding bị từ chối | `PinnedRoutingTests`; upload → publication → reader/cleanup; binding đổi không retarget phiên cũ. |
| Direct download ON/OFF | `PresignedDownloadTests` override trực tiếp; verified version/checksum/size và cookie-isolated public endpoint | Scope/ACL revoked, bad version/hash, flag-off backend fallback; không đòi real provider. |
| Control Center, LAB/runtime probes ON/OFF | Scoped profile, explicit confirmation, runtime FakeS3, ownership receipts/browser digest/cleanup | Routing và runtime qualification suites; deny grants/confirmation/flag/cleanup failures. |
| Topology ON/OFF | InventoryFixture, position-only layout, expected revision | Layout negative CSRF/scope và concurrency checks. |
| Monitoring ON/OFF | Metrics fixture, generation/staleness, monitor grant, SSE reauthorization | Telemetry fixture suite; không gọi exporter/SeaweedFS runtime. |
| Agent/destructive operations | Default OFF; chưa có agent execute feature; metadata operation vẫn dry-run theo constraints | Không bật execute hoặc tạo coverage claim cho feature chưa triển khai. |
| Live storage | Default integration gates bị vô hiệu hóa; phải `--live-storage` + explicit SeaweedFS gate ngoài CI | Negative CI/live parser test PASS; **không chạy live mode P1**. |

`infra/postgres-test.compose.yml` đã được chạy riêng với PG 18.6 (Debian 18.6-1.pgdg13+2), loopback 55432 và tmpfs; không mount serving/Filer volumes. Test credential chỉ tồn tại trong process và file local ignored của phiên. Sau các suite, query catalog trên **test service** cho số DB `test_bluedrive_%` còn lại là **0**. Không query/drop serving DB để teardown.

## 6. Test results trước/sau và lệnh

Python bên dưới là `.\.venv\Scripts\python.exe`; các commands mặc định không cần `DEBUG`/runtime flags trong shell. Chuẩn bị test PostgreSQL/password theo [DEVELOPMENT §4.1](DEVELOPMENT.md#41-postgresql-test-riêng).

| Kiểm tra | Trước / sau P1 | Trạng thái và giới hạn |
| --- | --- | --- |
| Reproduce runner cũ trên test DB riêng, `$env:DEBUG='true'` trước sửa | 614, failures=55, errors=20, skipped=19; **906.829s** | **FAIL baseline**, trùng đúng counts P0; không tái dùng thời gian/số liệu cũ làm test mới. |
| Isolated full, lần đầu | 614, errors=3, skipped=19; 757.447s | **FAIL trung gian**, ba AES process-key fixture errors; 75 lỗi cũ đã hết. |
| Isolated full cuối: `python -X utf8 infra/seaweedfs/regression.py` | 614, **0 failures/errors**, 19 skipped; **979.030s** | **PASS cho 595 tests thực thi**; 19 **SKIP** provider gates; DB test teardown. |
| Explicit enabled-fixture command §5 / CI | **72/72**, 0 skipped; 77.480s | **PASS**, subsuite của full, không chứng nhận provider thật. |
| `... regression.py security.tests` | **9/9**, 0 skipped; 0.175s | **PASS**, AES key fixture/tamper/unwrap; không đổi crypto. |
| `python -X utf8 -m unittest discover -s backend/tools -p 'test_*.py' -v` | **19/19**, 8.305s | **PASS**, gồm safety/history fixture và test settings/runner/security guards. |
| `python -X utf8 backend/manage.py check --settings securedrive.test_settings` | 0 issues | **PASS** trên test config. |
| `... manage.py makemigrations --check --dry-run --settings securedrive.test_settings` | No changes detected | **PASS**, không tạo/apply migration trên serving. |
| `python -m pip check`; bootstrap repair và rerun | No broken requirements; bản cài đã satisfied | **PASS**, version không thay, chưa phải fresh GitHub/Linux install. |
| `python -X utf8 backend/tools/check_repository_safety.py` | Working tree riêng | **PASS**, xem lần scan cuối ở §9; binary font không được coi là text scan. |
| `... check_repository_safety.py --staged` | Trước FAIL literal dòng 25; sau PASS | **PASS index**, chỉ stage seed_demo security fix. History vẫn có finding, không rewrite. |
| Zero discovery với label `securedrive` | Runner nonzero trước tạo DB test | **PASS guard**, không coi 0 test là suite PASS. |
| Frontend `npm.cmd run lint` | exit 0 | **PASS**. |
| `npx.cmd --no-install next typegen`; `npx.cmd --no-install tsc --noEmit` | Cả hai exit 0 | **PASS**. |
| 39 Node test files, `node --experimental-transform-types --test ...` | **159/159**, 0 skipped, 2648.2663ms | **PASS**, experimental/module warnings không bị che; không đổi ESM mode. |
| `npm.cmd run build` với Poppins local | Compile/typecheck, **40/40 static pages**, exit 0 | **PASS**, không fetch Google Fonts, không mock font. |
| Parse workflow YAML, job/settings/service/action pins | 3 jobs; permissions read-only | **PASS static/local equivalent**, không phải Actions remote run. |
| GitHub Actions mới trên remote | Chưa publish | **BLOCKED / NOT RUN** do không commit/push trong phạm vi này. |
| Browser visual/device, real S3/browser/finalizer/restore, production load | Không chạy | **SKIP**, ngoài P1; không suy nghiệm thu từ mock/healthy container. |

Raw test logs giữ local trong temp, không đưa trace/auth/config private vào repository. CSV chỉ có error type, tên test/subtest và evidence source; không chứa password, cookie, signed URL hoặc key. Suite duration là thời gian kiểm thử trên workstation, không là benchmark latency sản phẩm. Một lượt shell redirect gặp PowerShell NativeCommandError trước khi hoàn tất suite đã được thay bằng Python subprocess capture; chỉ các lượt có summary/teardown trên được tính kết quả.

## 7. File manifest P1

**Sửa 15 file hiện hữu**, giữ phần thay đổi có sẵn:

- `.gitignore`; `.github/workflows/verify.yml`; `backend/requirements.txt`.
- `infra/seaweedfs/regression.py`; `backend/tools/check_repository_safety.py`; `backend/tools/test_repository_safety.py`.
- `frontend/app/layout.tsx`.
- `AGENTS.md`; `MAP.md`; `README.md`; `backend/README.md`; `frontend/README.md`; `docs/DEVELOPMENT.md`; `infra/seaweedfs/README.md`; `docs/REFACTOR_P0_BASELINE_2026-11-16.md` (chỉ thêm link trạng thái tiếp nối).

**Tạo mới 14 file**, gồm cả patch review:

- `infra/bootstrap-python.ps1`; `infra/postgres-test.compose.yml`; `backend/securedrive/test_settings.py`; `backend/tools/test_test_settings.py`.
- `frontend/app/fonts/poppins/{Poppins-Regular,Poppins-Medium,Poppins-SemiBold,Poppins-Bold}.ttf`, `OFL.txt`, `README.md`.
- `docs/ADR-0011-isolated-test-baseline-and-local-fonts.md`; `docs/REFACTOR_P1_BASELINE_2026-11-16.md`; `docs/REFACTOR_P1_FAILURE_CLASSIFICATION_2026-11-16.csv`; `docs/REFACTOR_P1_CHANGES_2026-11-16.patch`.

**Index-only, không thay working file trong P1:** `backend/dashboard/management/commands/seed_demo.py`. Bản sửa đã có trước P1; chỉ đưa đúng 10 dòng diff bảo mật đã review vào index. Chưa stage các file P1 khác hoặc thay đổi baseline không liên quan.

`.python/`, `.venv/`, downloaded package/config recovery/test password và test logs là artifact local ignored, không là source bàn giao và không được force-add. Không tạo `backend/venv` hoặc venv thứ hai.

## 8. Security, khôi phục và điều kiện P2

- Production settings/auth/CSRF/RBAC/quota/storage guards và crypto source giữ nguyên; CI/test defaults không bật hoặc tắt flags của process phục vụ. Enabled tests giữ đầy đủ ready/pinning/denial assertions.
- Không đưa runtime key/credential vào test config. Test keys sinh ngẫu nhiên; legacy reader chỉ thấy key test trong chính test subprocess. `.env`, media, Filer/application data và S3 không bị chỉnh để chữa test.
- Source/index guard vẫn không thay secret scanner hoàn chỉnh: không chứng nhận binary fonts hoặc toàn history an toàn. Finding seed history và khả năng tài khoản demo từng dùng default cần xử lý theo phạm vi riêng; không tự rotate hoặc rewrite.
- Khôi phục source bằng reverse **patch P1 riêng** sau review, giữ nguyên user changes ngoài P1. Không reverse toàn bộ diff với HEAD. Có thể đổi lại loader Google khi cần rollback font nhưng sẽ đưa lại yêu cầu mạng khi build; không xóa OFL. Không tự bỏ sửa bảo mật seed_demo trong index.
- `.venv` đang chạy được nên ưu tiên giữ full base runtime; bản cfg trước repair chỉ để điều tra, đưa lại cfg cũ sẽ tái hiện lỗi base path đã mất. Không đổi Python hệ thống để rollback.
- Test PostgreSQL chỉ có dữ liệu fixture tmpfs. Sau kiểm thử, dừng đúng service/project `bluedrive-tests`; không chạy `down -v`, xóa object hoặc cleanup dữ liệu khác. Tạo lại test service cần test password khớp lifecycle của chính service đó.

**Đánh giá P2:** local engineering baseline đã đạt các checks P1. Tuy nhiên acceptance **GitHub Actions remote còn mở**; khuyến nghị review patch/curate baseline và đợi workflow remote PASS trước nghiệm thu đầy đủ P1/bắt đầu P2. Nhiệm vụ hiện tại cấm commit/push nên không tự hoàn tất gate đó. Enterprise/My Drive/provisioning/approval/CSE decisions của P0 vẫn cần scope riêng, không được xem là đã giải quyết nhờ CI xanh.

Workflow tái hiện → inventory từng failure → isolate settings/DB → run full/enabled matrix → review patch có thể gói thành phần mở rộng của project skills khi lặp lại; chưa tạo skill mới hoặc bắt đầu P2.

## 9. Review cuối

Source snapshot ngoài 15 file P1 có **627 file giữ nguyên hash**; HEAD không đổi và index chỉ khác ở đúng `seed_demo.py`. Baseline của cả 15 file được patch so sánh đã khớp SHA-256 trước P1. Các model/migration/auth/access/quota/crypto services và frontend design tokens giữ nguyên; không ghi đè thay đổi của người dùng.

Đã chạy Django system/migration consistency cuối, guard tests, lint/types/Node/build, safety working tree/index và `git diff --check`. CSV có đủ 75 records; đối chiếu discovery xác nhận 61 affected methods vẫn có mặt, không bị skip. Patch riêng được kiểm reverse bằng `git apply --check` trên bản sao scope P1; link/path và whitespace của source/docs mới được kiểm riêng vì nhiều file untracked không nằm trong `git diff`.

Ngoại lệ formatting có bằng chứng: `frontend/app/fonts/poppins/OFL.txt:21` có trailing whitespace nguyên bản upstream; giữ nguyên license với SHA-256 đã xác minh trong font README. Không có whitespace/encoding finding ở source hoặc tài liệu P1 tự viết. Scan cuối: working tree **657 text/5 binary chưa scan, 0 findings/blocked**; index **419 text/1 binary chưa scan, 0 findings/blocked**. Binary fonts có provenance/checksum, không được gọi là đã secret-scan text.

Test service `bluedrive-tests-postgres-1` được dừng riêng sau khi số test DB còn lại là 0; tmpfs `/var/lib/postgresql` đã xác minh, không xóa Docker volumes. Runtime serving/Filer/SeaweedFS không bị restart hoặc cleanup. Không commit/push/deploy hoặc thực thi P2–P8. Gate GitHub Actions remote vẫn **BLOCKED / NOT RUN** theo ranh giới nhiệm vụ.

## 10. P1.1 — Final Hardening & Acceptance (16/11/2026)

Phần 1–9 giữ bằng chứng P1 ban đầu. Phần này ghi kiểm chứng mới của P1.1, không tái dùng số test cũ làm kết quả mới. Phạm vi chỉ environment/test target/CI/security/handoff; không sửa nghiệp vụ, provisioning, Tenant, Workspace hoặc Storage Routing. Nghiệm thu toàn bộ P1 vẫn **BLOCKED** đến khi GitHub Actions remote PASS trên commit thực chứa candidate đã review.

### 10.1 Root cause và rủi ro đã đóng

| Vấn đề xác minh ở P1 | Sửa trong P1.1 / bằng chứng |
| --- | --- |
| `patch.dict(os.environ, ..., clear=True)` chỉ cách ly lúc import; khi hết context, runtime environment quay lại. | Test settings giữ allowlist suốt process. dotenv tiếp tục disabled, không phục hồi aliases/token/AWS/libpq/proxy runtime. Chỉ key AES test được cấp cho reader legacy; shell cha/serving process không bị đổi. |
| `connection_profiles.build_client`, pinned adapter factory và `prometheus.query` đọc credential từ `os.environ` sau import. | Negative subprocess tests nạp sentinel runtime: storage từ chối trước gọi boto3, monitoring từ chối trước HTTP; botocore credential chain trả `None`. Fixture vẫn cấp credential bằng `patch.dict` theo scope và được thu hồi sau scope. Không sửa service nghiệp vụ. |
| Module settings runtime đã cache có thể đi vòng nguồn cấu hình test. | Test settings yêu cầu process mới và từ chối import khi `securedrive.settings` đã có trong module cache. Có negative test riêng. |
| Prefix control DB không bảo đảm đúng server; HOST/PORT/USER tùy ý vẫn được chấp nhận. | Hai profile source-controlled cố định: local `127.0.0.1:55432`, CI `127.0.0.1:5432`; cùng DB `bluedrive_test_control`, role `bluedrive_test`. Override lệch bị chặn trước connect; hostaddr và passfile cố định, không nhận DSN/DNS/multi-host. |
| Chưa kiểm lại identity trước lifecycle tạo/xóa DB. | Init SQL chỉ mount read-only vào test tmpfs, hoặc chạy trên CI service riêng. Runner đọc marker + current database/current role/server port, kiểm config/options/UUID trước setup và teardown. Thiếu marker hoặc config đổi thì fail closed, không tự ghi marker/drop DB để chữa lỗi. |
| `manage.py test` có thể bỏ qua guard của entry point. | `TEST_RUNNER` từ chối trước tạo DB và hướng dẫn dùng `infra/seaweedfs/regression.py`. Django check/migration consistency vẫn dùng test settings bình thường. Không xóa test hoặc đổi assertion để lấy PASS. |
| Live mode chưa buộc xác nhận scope/labels; app initialization có thể nhìn DB runtime. | Cần `--live-storage --confirm-live-storage <approved-fixture-scope> <labels>` + integration gate, CI luôn chặn. DB test được ghim trước `django.setup()/app.ready()`; chỉ storage settings lấy từ runtime. Negative test dùng module giả, không đọc `.env` hoặc gọi provider thật. |
| Checkout sạch mất thư mục `backend/static` rỗng. | Bản sao sạch tái hiện `staticfiles.W004`; thêm `backend/static/.gitkeep`, chạy lại system/migration checks hết warning. Không sửa UI hoặc settings production để né lỗi. |

Allowlist giữ các biến OS thiết yếu (`SYSTEMROOT/WINDIR/PATH/TEMP/TMP/LANG/LC_ALL/TZ`), chỉ báo CI/output và contract test DB. Credential files AWS/boto/libpq trỏ về null device, metadata provider AWS disabled. Đây là cách ly cấu hình cho regression, không phải sandbox chống mã test độc hại. Marker public chống chọn nhầm target, không thay password hoặc xác thực operator.

Giống phòng kiểm định giữ chìa khóa riêng suốt ca, kiểm biển nhận diện kho mẫu trước khi mở và đóng. Đổi chìa khóa chỉ trong lúc mở cửa vẫn có thể khiến người đến sau lấy nhầm hàng thật.

### 10.2 Files thay đổi và Git handoff

Các file có sẵn tại đầu P1.1 được sửa đúng scope:

- `backend/securedrive/test_settings.py`, `backend/tools/test_test_settings.py`: persistent environment, cache/bypass guards và negative tests.
- `infra/seaweedfs/regression.py`: target/identity lifecycle guards, live scope confirmation và DB pin trước app initialization.
- `infra/postgres-test.compose.yml`, `.github/workflows/verify.yml`: port/profile cố định, init marker của test service; CI ghim Node 24.18.0 thay major trôi 24 (đúng bản đã kiểm local).
- `AGENTS.md`, `MAP.md`, `backend/README.md`, `docs/DEVELOPMENT.md`, `infra/seaweedfs/README.md`, `docs/ADR-0011-isolated-test-baseline-and-local-fonts.md` và báo cáo này: đồng bộ contract/lệnh/gate mới.

File mới: `backend/securedrive/test_environment.py`, `backend/static/.gitkeep`, `infra/postgres-test-init.sql`, [delta P1.1](REFACTOR_P1_1_CHANGES_2026-11-16.patch) và [candidate source manifest](REFACTOR_P1_1_HANDOFF_2026-11-16.csv). Manifest ghi tên file/hash/trạng thái scope để review candidate gồm cả baseline có sẵn và các deletion đã tồn tại trước P1.1; không phải lệnh stage toàn bộ. Hai artifact patch/manifest không tự liệt kê hash của chính chúng.

Đối chiếu snapshot P1.1: **12 file có sẵn được sửa**, **650 file có sẵn giữ nguyên hash**, **9 deletion có sẵn giữ nguyên trạng thái**; thêm 3 source files và 2 artifact review. Không có file frontend/auth/model/migration/quota/storage service nào bị sửa. Manifest gồm 665 source files + 9 deletion rows = 674 rows, không tính hai artifact tự sinh.

HEAD đầu P1.1: `d968ebffa0d17f4fce81c2b2f56af5021e60e070`. Index snapshot SHA-256: `fec2be796e888a1d10eaf3632d3a10557b2706287038dc68537ed4546d3a83c9`. P1.1 không stage thêm file nào. Không reset/stash/commit/push hoặc rewrite history.

**`backend/dashboard/management/commands/seed_demo.py` thuộc phạm vi Git bàn giao.** Đây là bản sửa pre-P0 đã được stage riêng trong P1, không phải sửa mới P1.1 và không nằm trong patch P1. Index khớp working tree, khác HEAD; blob index `f47e9fe7018c2c66f9a21a2e64fe582e3a300bb7`, SHA-256 `0596ac35ff45b1151d94414dc6f9ef1eedc712ee7c486099c97866bfd09a7e6b`. Manifest có dòng riêng cho staged security fix này. Người dùng cần giữ file này trong commit candidate cùng các thay đổi đã review; không chỉ áp patch P1/P1.1 rồi bỏ qua index. HEAD vẫn có credential-literal ở dòng 25; không chép literal/diff xóa secret vào báo cáo, không rewrite history hoặc rotate tài khoản runtime.

**Checkout handoff:** `.github/workflows/verify.yml`, test settings và `backend/infrastructure/models.py` chưa tồn tại trong HEAD; nhiều module/migration/caller baseline đang untracked hoặc modified từ trước. Patch P1 và P1.1 là delta với working baseline tương ứng, không phải một patch tự đủ áp thẳng vào HEAD cũ. Candidate sạch được export từ source working tree hiện tại, không có private env/data/dependencies. Trước commit/push, review manifest và curate đầy đủ baseline dependencies, P1, P1.1 cùng seed fix; chỉ commit riêng workflow sẽ không tạo checkout chạy được. Không tự stage toàn bộ hoặc trộn thay đổi người dùng một cách mù quáng.

### 10.3 Kiểm thử mới

Tất cả lệnh Python dùng chính `.venv` Python 3.12.10; không tạo venv thứ hai. PostgreSQL chỉ là project `bluedrive-tests` tmpfs, không serving/Filer. Các suite đồng thời có UUID DB khác nhau. Test flags mặc định OFF; enabled fixtures dùng `override_settings` và scoped binding/FakeS3 theo ma trận P1. Không hạ security/ACL/quota/constraints/hashers/assertions. Đối chiếu snapshot: 63 file regression trong tám app giữ nguyên hash; chỉ guard tests ngoài suite app được mở rộng. Assertions so sánh runtime secret/password giữ sentinel trước sanitize, đồng thời kiểm password test đúng contract; không biến assertion thành so sánh với biến đã bị xóa.

| Nhóm | Kết quả P1.1 |
| --- | --- |
| Tools: `python -X utf8 -m unittest discover -s backend/tools -p 'test_*.py' -v` | **PASS 27/27**, 0 skip, 16,977s: 14 repository safety + 13 environment/target/live guards; tăng từ 19 của P1. |
| Django system check + `makemigrations --check --dry-run --settings securedrive.test_settings` | **PASS**, 0 issues/0 migration changes; bản sao sạch cũng PASS sau giữ static directory. |
| Security PostgreSQL: `regression.py security` | **PASS 9/9**, 0 skip, 0 failures/errors; tạo/hủy DB đã qua marker guards. |
| Full Django working tree | **PASS**: 614 discovered = 595 thực thi + 19 provider SKIP, **0 failures / 0 errors**, 1110,311s. |
| Full Django bản source sạch, code cuối | **PASS**: 614 discovered = **595 thực thi + 19 provider SKIP**, **0 failures / 0 errors**, **1030,517s**; đây là lượt nghiệm thu code cuối, khớp hash source harness bàn giao. |
| Explicit enabled-fixture labels ở §4.1 DEVELOPMENT | Lượt đầu **PASS 72/72**, 0 skip; lượt code cuối **PASS 72/72**, 0 skip, 74,903s. Không cộng hai lượt thành số test khác nhau. |
| PostgreSQL negative checks (lệnh runner thật) | **PASS**: zero discovery bị từ chối trước CREATE; host ngoài profile bị từ chối trước connect; tập DB test trước/sau không đổi. Ca thiếu marker trên PostgreSQL test thật cũng bị chặn trước CREATE; marker được khôi phục, 0 DB UUID còn lại. |
| Frontend working tree: lint, typegen, `tsc --noEmit`, Node tests, production build | **PASS**, 159/159 Node tests, 0 skip; build 40/40 static pages. |
| Frontend source sạch, không `.env.local`/`node_modules` lúc bắt đầu | **PASS**: `npm ci --ignore-scripts` cài 383 packages từ lockfile; lint/typegen/types, 159/159 tests, build 40/40. Không đổi font/UI/dependency. |
| Dependency compatibility | **PASS** `pip check`; tải đủ 24 wheel đã ghim cho CPython 3.12/Linux manylinux2014 x86_64, không cài đè package hiện hữu. |
| Workflow | **PASS local** YAML, 3 jobs, action SHA pins, read-only contents, checkout không giữ credentials, profile CI + marker step, Node 24.18.0 có trong [release chính thức](https://nodejs.org/download/release/v24.18.0/SHASUMS256.txt). Không thay remote run bằng kết quả parse YAML. |
| Working-tree security scan / index scan | **PASS độc lập**: working tree 662 text / 5 binary chưa scan; index 419 text / 1 binary chưa scan; cả hai 0 findings / 0 blocked. |
| History scan: `check_repository_safety.py --history HEAD` | **FAIL còn mở**: 29 commits, 740 unique blobs; 737 text / 2 binary chưa scan, 4 findings, 0 blocked. Không rewrite history hoặc rotate credential runtime. |
| Whitespace/delta review | **PASS** working-tree/index `git diff --check`; UTF-8/whitespace và local doc links; patch forward/reverse `git apply --check` trên bản sao review, không apply vào user source. |
| GitHub Actions remote trên candidate | **BLOCKED / NOT RUN**: chưa có commit/push theo ranh giới nhiệm vụ. |

Fresh local evidence ở `%TEMP%/bluedrive-p11-{full,clean-full,enabled,final-enabled,frontend,clean-frontend,final-postgres,negative-postgres,marker-negative}-20261116.log`; log chỉ giữ local, không force-add. Bản sao source/caches/wheels ở `.python/p11-*` ignored; không có runtime `.env` trong source export. Wheel download và npm ci lần đầu bị sandbox network từ chối; chạy lại cùng thao tác giới hạn bằng escalation đã được automatic review cho phép và thành công. Đây là hạn chế môi trường kiểm tra, không phải sửa dependency để bỏ qua failure.

Discovery độc lập xác nhận 614 IDs; 61 affected methods của CSV P0 vẫn có mặt và không skip. 19 provider tests gồm `files.tests.test_minio_storage_integration` **9**, `files.tests.test_seaweedfs_integration` **8**, `files.tests.test_seaweedfs_finalizer_integration` **2**. Chúng giữ **SKIP**, không tính PASS: MinIO/SeaweedFS cần provider thật và identity/fixture được duyệt; P1.1 không bật live hoặc cấp quyền ghi provider. Không thay skip thành mock pass. Node báo warning module-type đã có; npm báo eslint 9.39.5 deprecated. Không nâng dependency ngoài scope; các warning này không làm giảm số test hoặc bỏ build.

### 10.4 Remote Actions, rủi ro còn mở và điều kiện P2

Đã đối chiếu workflow thực tại `.github/workflows/verify.yml`, dependency lock/pins, ba job và source cần cho checkout. Các SHA actions được kiểm tra tại upstream chính thức: [checkout](https://github.com/actions/checkout/commit/3d3c42e5aac5ba805825da76410c181273ba90b1), [setup-python](https://github.com/actions/setup-python/commit/6d4fd22b20465ccc0f7354476588e8df7c9ca0e0), [setup-node](https://github.com/actions/setup-node/commit/949feb2413d6458794dcd2491c4babbbce0c15c1). Read-only GitHub connector trả 0 PR-triggered runs cho HEAD hiện tại; API này chỉ phủ PR-triggered/first page, không dùng để kết luận toàn bộ lịch sử Actions. Quan trọng hơn, HEAD chưa chứa P1/P1.1 nên run cũ không nghiệm thu candidate này.

Người dùng review/commit/push candidate đã curate, rồi xác nhận **cả repository-safety, backend và frontend jobs PASS trên đúng commit SHA**. Khi đó ghi URL run, SHA, kết quả từng job và số test/skip vào phần tiếp nối này. Nếu remote FAIL, giữ P1 chưa hoàn tất và sửa failure có evidence trong scope. Không tự dispatch/push/commit hoặc đánh dấu remote PASS.

History scan mới mở rộng ngoài seed-only review P1: `backend/dashboard/management/commands/seed_demo.py:25` (blob `8e71f6c8befc`, seen `d968ebffa0d1`) và `:24` (blob `3e4b401b8079`, seen `f312498cd5e4`); `securedrive/settings.py:23` (blob `2e55a20ba2d1`, seen `322fa08e53b3`) là credential-literal; `backend/accounts/test_admin_files_api.py.bak` (blob `257ee385e76e`, seen `da5576fb2b7c`) là private-artifact theo tên. Scanner không mở blob private, không in giá trị. Đây là findings lịch sử đã xác minh về source/location; chưa chứng minh credential cũ còn hiệu lực runtime. Cần security disposition riêng do operator review; không tự rewrite/rotate trong P1.1. CI mặc định vẫn quét working tree/index, không tuyên bố toàn history sạch.

Rủi ro còn mở: remote Linux Actions chưa được nghiệm thu; candidate commit chưa được curate từ dirty baseline; 19 provider tests chưa chạy live; credential cũ vẫn tồn tại trong history và trạng thái account runtime không được xác minh/rotation trong nhiệm vụ này. History scan hiện FAIL như trên; source/index PASS không thay kết luận đó. Binary không được secret-scan text, scanner không chứng nhận mọi loại secret. Các gate provider/provisioning/CSE/Enterprise không nằm trong P1.1 và không được suy PASS từ harness.

Rollback: review reverse delta P1.1 trên đúng baseline P1, không reverse toàn bộ diff với HEAD; giữ staged seed security fix và các thay đổi có sẵn. Rollback hardening sẽ mở lại rủi ro environment/target; không coi đó là phương án vận hành bình thường. Không cần migration, key rotation hoặc thay serving/Filer/storage endpoint. Khi kiểm thử xong chỉ dừng đúng PostgreSQL test service sau khi xác nhận không còn DB UUID của các suite; không xóa volumes hoặc cleanup dữ liệu thật.

**P2 chưa đủ điều kiện bắt đầu** đến khi các kết quả local cuối đã chốt, remote Actions PASS đúng candidate commit và người phụ trách security có disposition cho findings history (không tự yêu cầu rewrite/rotation trong P1.1). Dừng ở P1.1. Quy trình isolation → target identity guards → negative tests → clean-source regression → scoped Git handoff có thể bổ sung vào project skill hiện có khi lặp lại; chưa tạo skill hoặc triển khai P2.

Kết thúc P1.1 local: toàn bộ checks được yêu cầu đã có kết quả ở §10.3. Sau ca âm thiếu marker và khôi phục marker, xác nhận **0 DB test UUID còn lại**, rồi chỉ dừng `bluedrive-tests-postgres-1`; không xóa volumes, không stop/restart serving hoặc Filer. Local implementation/checks đã chốt; toàn bộ P1 vẫn **chưa hoàn tất remote acceptance**. Không commit/push/deploy hoặc bắt đầu P2.

## 11. P1.1 Final Acceptance — live gate, history disposition và Git candidate

Phần này tiếp nối yêu cầu final acceptance, không làm lại P0/P1. Phần 10 giữ bằng chứng lượt trước; contract live ở đây thay quyết định nạp runtime settings của lượt đó. Không thay business logic, frontend, model/migration, quyền/quota/storage routing hoặc dữ liệu phục vụ. Bổ sung CI runner lifecycle cho suite không dùng database, không chạy provider thật. Chưa commit/push/deploy; không bắt đầu P2.

### 11.1 Live-storage chỉ chạy provider gate có tài nguyên riêng

Rủi ro đã xác minh: nhãn `security`/app/path bất kỳ trước đây vẫn được runner live chấp nhận, trong khi runtime settings có MEDIA_ROOT/email/endpoint phục vụ. Chỉ pin PostgreSQL chưa đủ cách ly các nơi test có thể ghi. Chọn tái sử dụng test settings đã cách ly và allowlist provider env thay vì sao chép toàn bộ runtime config rồi blacklist từng tài nguyên. Giống cấp chìa khóa đúng phòng mẫu và tủ hồ sơ riêng, không chỉ dán nhãn lên mẫu nhưng để người kiểm thử dùng cả kho thật.

Sửa `infra/seaweedfs/regression.py` và `backend/tools/test_test_settings.py`; CI bổ sung `Runner lifecycle without database-using tests` để giữ nhánh teardown cho suite không cần DB. `old_config` rỗng kiểm control target thay vì giả định UUID DB đã được tạo, không bỏ marker validation:


- Chỉ nhận `files.tests.test_seaweedfs_integration.SeaweedFSIntegrationTests` và `files.tests.test_seaweedfs_finalizer_integration.SeaweedFSFinalizerIntegrationTests`. Hai module tương ứng được nhận làm alias, rồi chuẩn hóa về đúng classes; không discover toàn module. Hai LoopbackHTTPTests cùng module vẫn được chạy trong full suite và CI gate riêng, không bỏ coverage khi thu hẹp live labels. Chặn label app/method/path/wildcard/MinIO hoặc nhãn trộn ngoài allowlist trước `django.setup()`, đổi cwd, tạo media, kết nối DB/storage/email hay ghi file.
- Cả default/live dùng `securedrive.test_settings`: không đọc serving dotenv, không dùng module runtime cache, giữ DB target/UUID/marker/credential guards và generated test keys. Chỉ cấp lại năm `SEAWEED_S3_*` endpoint/bucket/credential, hai gate integration/write và frontend origin header đã kiểm tra. AWS/libpq fallback, proxy và các aliases runtime khác vẫn bị loại bỏ.
- `--confirm-live-storage` phải là scope chữ thường/số/gạch ngang 1–32 ký tự; bucket phải đúng `bluedrive-test-<scope>`. Credential không được rỗng và phải là identity fixture do operator duyệt. Không tự tạo bucket, đổi credential/grant hoặc cấu hình provider.
- Internal origin chỉ HTTP `127.0.0.1` với port tường minh; public origin chỉ IP đó hoặc `s3.localhost` với port. Chặn userinfo/path/query/fragment/whitespace, origin ngoài loopback và URL lỗi. HTTP helper ghim TCP `s3.localhost` về IP loopback, giữ host/query đã ký. Không chấp nhận DNS arbitrary cho đường SDK internal.

| Tài nguyên có thể ghi/gọi | Nguồn và kiểm soát cuối |
| --- | --- |
| PostgreSQL create/migrate fixture/drop | Profile local/CI cố định, control marker/role/options kiểm trước setup và teardown, UUID chưa tồn tại; không serving/Filer. |
| MEDIA_ROOT, AES legacy/cache/spool | Temporary directory `bluedrive-tests-media-*` và tempfile của test process; không `backend/media`. AES key test sinh ngẫu nhiên, không runtime key. |
| Email/account invitation | `django.core.mail.backends.locmem.EmailBackend`, không SMTP runtime. Users/membership/quota/audit chỉ trong DB fixture. |
| S3 PUT/multipart/copy/delete/list versions | Chỉ bucket fixture đúng scope trên loopback; keys do adapter/test sinh ngẫu nhiên, cleanup đúng key/upload/version đã tạo. Không liệt kê/xóa bucket hoặc dữ liệu ứng dụng. |
| Bucket administration/cross-bucket | Giữ nguyên negative assertions: anonymous/sai credential/cross-bucket và put bucket CORS/versioning phải bị deny. Identity fixture không được có quyền quản trị bucket; harness không sửa policy cho test pass. |
| Finalizer/API/download | DRF APIClient trong process, worker gọi inline; giữ byte/SHA-256/version/quota assertions. Global profile registry rỗng, flags test xác định rõ; provider settings chỉ được fixture override trong test hiện có. |
| Master/monitoring/scanner/SDK fallback | Master test loopback port 9, storage global `.invalid`, runtime registry/probes OFF; scanner hook rỗng, AWS files/metadata disabled, env token/proxy runtime không còn. Không có endpoint SMTP/monitoring/scanner/runtime worker được kế thừa. |
| CORS/frontend/logging | Origin chỉ header localhost/127.0.0.1 port 3000, không gọi frontend thật; logging dùng console, không file log phục vụ. |

Đã trace cả hai provider classes và callers finalization/storage, không sửa assertions hoặc dịch vụ nghiệp vụ. Prefix/loopback không chứng nhận ownership hoặc quyền storage của operator: live vẫn **NOT RUN** trong nhiệm vụ này; chỉ được chạy sau khi bucket/identity fixture, CORS/versioning và quyền ghi/dọn đã được duyệt riêng. Không dùng credential phục vụ dù endpoint cùng máy. 19 provider tests default tiếp tục SKIP, không biến thành PASS.

Đồng bộ contract/lệnh trong `AGENTS.md`, `MAP.md`, `backend/README.md`, `docs/DEVELOPMENT.md`, `infra/seaweedfs/README.md` và bổ sung ADR-0011 hiện có. Runbook dùng `$ApprovedFixtureEnv`, không nạp serving storage env vào gate. Không tạo thêm tài liệu quyết định trùng lặp.

### 11.2 Phân loại đủ bốn finding history, không in secret

Review từng blob xác định, dùng AST/so sánh trong memory và chỉ xuất tên biến/call flow/boolean; không in literal, username/email hoặc dump source. Riêng `.bak` được review có mục tiêu theo yêu cầu này; scanner chung vẫn giữ nguyên quy tắc không mở blob private. Không đọc serving `.env`, đăng nhập bằng password cũ, query/đổi account runtime, hoặc thay khóa để suy ra trạng thái sử dụng hiện tại.

| Finding | Phân loại và evidence | Rotation/thu hồi | History trước publish / trạng thái |
| --- | --- | --- | --- |
| `seed_demo.py:25`, blob `8e71f6c8befc`, seen `d968ebffa0d1` | **Demo bootstrap credential có thể dùng thật**, không phải password chỉ tồn tại trong TestCase. `DEFAULT_PASSWORD` → argparse `--password` default → biến `password` → `user.set_password(password)`. | Cần operator inventory các môi trường từng chạy seed; thay password hoặc disable các account còn dùng default và xử lý sessions/access liên quan. Không giả định sửa source đã đổi account. | **OPERATOR REVIEW REQUIRED**. Không publish candidate/history rộng hơn khi chưa xác nhận default đã được retire hoặc chưa từng được dùng. Sau xác nhận thu hồi/không sử dụng, rewrite không tự động bắt buộc; cần risk acceptance hoặc chính sách history riêng. |
| `seed_demo.py:24`, blob `3e4b401b8079`, seen `f312498cd5e4` | Cùng call flow operational; so sánh in-memory chứng minh **cùng một literal** với finding trên. Hai blobs không phải hai password cần rotate độc lập. | Cùng kế hoạch retire/account review bên trên, không reset hàng loạt hoặc chạy lại seed. | **OPERATOR REVIEW REQUIRED**, cùng exposed credential. Không xóa history để thay thế việc bảo vệ account đang hoạt động. |
| `securedrive/settings.py:23`, blob `2e55a20ba2d1`, seen `322fa08e53b3` | Literal `SECRET_KEY` có prefix development Django; source cũng có DEBUG literal. Điều đó chứng minh nguồn dev, **không chứng minh chưa dùng ký session/token ở môi trường thật**. Current source yêu cầu env, nhưng active deployment/key fallbacks chưa được kiểm chứng. | Operator so sánh an toàn deployment configs/current key/fallbacks với key lộ, không công bố giá trị. Nếu từng/đang dùng: thay signing key có kế hoạch, retire fallback phù hợp và xử lý signed sessions/tokens chịu ảnh hưởng. Không tự đổi AES/storage key hoặc runtime config. | **OPERATOR REVIEW REQUIRED**. Nếu không chứng minh unused/retired thì chặn publish. Nếu đã retired/không dùng và risk được chấp nhận, rewrite không tự động cần thiết; nếu policy yêu cầu history sạch, chuẩn bị scrub/clean-history phương án riêng có backup/phối hợp. |
| `backend/accounts/test_admin_files_api.py.bak`, blob `257ee385e76e`, seen `da5576fb2b7c` | **Backup source TestCase**, không phải DB backup/dump hay runtime credential file. AST là `AdminFilesAPITests(TestCase)`, `setUp` tạo hai user bằng password literals fixture, APIClient gọi API trong process; không top-level operational calls. Hai fixture literals khác exposed demo default, không thấy token/private-key/URL-password patterns. | **Không cần rotation theo evidence hiện có**: đây là fixture test DB. Không suy rộng sang mọi file `.bak`; scanner policy giữ nguyên. | **DISPOSITION: INFORMATIONAL / NO SECRET REMEDIATION** cho blob này. File đã vắng trong HEAD/index/current candidate; không đưa backup vào commit. Không cần rewrite chỉ vì finding tên `.bak`; cleanup history nếu có là hygiene/policy riêng. |

Có **4 findings theo blob/path nhưng 2 loại credential material có khả năng dùng thật**: một demo password dùng chung giữa hai seed blobs, một development signing key. Backup-source finding đã được phân loại; ba credential rows còn chờ operator disposition, không gọi là đã rotate/thu hồi.

Exposure: local cached `origin/main` là `664ffb8de2d279776812a9b548099dc02a2dda2b`; graph local cho thấy seed-old và settings commit là ancestor. Read-only GitHub connector đã đọc được [chính commit đó](https://github.com/binos2303/BlueDrive/commit/664ffb8de2d279776812a9b548099dc02a2dda2b), chỉ giữ metadata, không xuất diff. Như vậy không thể coi credential lịch sử là chắc chắn chỉ còn local. Chưa xác minh visibility/forks/clones hay remote main tip mới nhất; không fetch/đổi refs. Blob seed-new/backup không được khẳng định đã nằm trên remote chỉ từ cached ref.

**Khuyến nghị trước push:** không push/expand visibility của history hiện tại cho tới khi operator xác nhận retire/unused của hai credential materials và ghi disposition. Theo [GitHub guidance](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository), ưu tiên revoke/rotate credential bị lộ; rewrite có hệ quả tới clones/SHAs và không thay thế bước đó. [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/#secret-key) yêu cầu signing key được giữ bí mật, tách production và retire fallback đúng lúc. Không tự rewrite, force-push, rotate hoặc vô hiệu user/session trong nhiệm vụ này. History scanner vẫn có thể FAIL raw findings đã biết dù source/index PASS; disposition không sửa scanner để che finding.

### 11.3 Git candidate: paths đầy đủ theo trách nhiệm

Đầu lượt acceptance, đối chiếu **674/674 rows manifest**, 0 hash/deletion mismatch với working tree. HEAD vẫn `d968ebffa0d17f4fce81c2b2f56af5021e60e070`; index hash giữ nguyên giá trị ở §10.2, staged file duy nhất là `backend/dashboard/management/commands/seed_demo.py`, khớp working tree. Không `git add .`, stage thêm, reset, stash, commit hoặc push.

Đã mở rộng **manifest hiện có**, không thêm tài liệu song song: thêm `commit_group`, `git_action`, `commit_decision`, `review_reason`. Mỗi source path có quyết định; `KEEP_HEAD` là file đã có trong HEAD, cần tồn tại trong checkout nhưng không cần stage lại. `EXCLUDE` là bỏ **working-tree delta/artifact** khỏi candidate, không xóa file và không untrack source đã có trong HEAD.

| Nhóm | Nội dung / vì sao cần | Inventory rows | Paths có delta phải review để commit |
| --- | --- | ---: | ---: |
| `G0_REPOSITORY` | Root/backend/frontend ignore rules để private env/dependency/output không vào Git | 3 | 2 MODIFY |
| `G1_BACKEND` | Tám apps, settings/URLs/callers/models/migrations/templates/assets, requirements và staged seed security fix | 208 | 34 ADD + 29 MODIFY + 1 STAGED = 64 |
| `G2_FRONTEND` | App Router, components/helpers/design assets, Poppins + OFL, frontend configs/manifests/lockfile | 217 | 49 ADD + 85 MODIFY + 5 DELETE = 139 |
| `G3_VERIFICATION` | GitHub workflow, Python bootstrap/test PostgreSQL init, runner/settings/guards, app/Node/e2e tests/scripts | 128 | 65 ADD + 15 MODIFY + 1 DELETE = 81 |
| `G4_INFRASTRUCTURE` | Existing provider/operator/lab source và 3 MinIO deletions có sẵn; không cấp quyền chạy/provision/deploy | 18 | 15 ADD + 3 DELETE = 18 |
| `G5_CONTEXT` | AGENTS/MAP/project skills/README, P0/P1/P1.1 reports, ADRs, development/runbooks và context source đã có | 80 | 72 ADD + 8 MODIFY = 80 |
| `X_LOCAL` | Editor/máy cá nhân/design-tool critique; giữ local delta | 3 | EXCLUDE |
| `X_EVIDENCE` | Raw operational inventory/CLI và generated audit JSON; cần sanitization/review riêng nếu muốn publish | 17 | EXCLUDE |

Manifest có **654 INCLUDE rows = 384 delta paths + 270 KEEP_HEAD**, trong đó 9 DELETE là trạng thái đã có trước nhiệm vụ. Thêm hai derived artifact paths ghi rõ bên dưới: tổng danh sách commit review là **386 delta/artifact paths**, không phải lệnh stage toàn bộ baseline. Các ADD/MODIFY baseline phụ thuộc lẫn nhau; chỉ commit patch P1/runner/workflow sẽ thiếu apps, migrations và frontend callers. Đây là review tính đầy đủ đường dẫn/dependency/test coverage, không thay approval nghiệp vụ cho mọi thay đổi dirty baseline của người dùng.

Các dependencies dễ bỏ sót đã giữ trong INCLUDE: toàn package `backend/infrastructure/` (kể cả migrations/URLs/models/services/tests), `backend/files/storage_routing.py`, migrations files `0016_storagelocation_provider_version_id.py`, `0017_pin_storage_targets.py`, `0018_s3_only_provider.py`, `backend/folders/tree_service.py`, frontend route/service/provider additions đang được callers import, `backend/static/.gitkeep`, Poppins TTF/OFL/README, `backend/requirements.txt`, frontend package/lock/config, `.github/workflows/verify.yml`, test settings/environment/guards, `infra/postgres-test-init.sql` và PostgreSQL Compose. `seed_demo.py` staged fix phải có trong commit dù không nằm trong patch P1.

Hai derived artifact paths thuộc `G5_CONTEXT/INCLUDE`, không tự chứa hash đệ quy của chính chúng trong CSV:

```text
docs/REFACTOR_P1_1_HANDOFF_2026-11-16.csv
docs/REFACTOR_P1_1_CHANGES_2026-11-16.patch
```

Lấy **danh sách Git paths chính xác theo nhóm**, chỉ đọc, không stage:

```powershell
Import-Csv docs/REFACTOR_P1_1_HANDOFF_2026-11-16.csv |
  Where-Object { $_.commit_decision -eq 'INCLUDE' -and $_.git_action -ne 'KEEP_HEAD' } |
  Sort-Object commit_group,path | Select-Object commit_group,git_action,path
```

EXCLUDE cụ thể, không xóa hoặc discard local files:

```text
.vscode/settings.json
.impeccable/critique/2026-11-07T06-25-28Z__frontend.md
.impeccable/critique/2026-11-08T01-14-09Z__frontend.md
docs/UI_AUDIT_DETECTOR_2026-11-07.json
docs/UI_FIXES_DETECTOR_2026-11-07.json
docs/roadmaps/storage-control-center-2026-11-08/MANIFEST.json
docs/task01-evidence/compose-static-check.txt
docs/task01-evidence/cutover-inventory.json
docs/task01-evidence/git-status-before.txt
docs/task01-runtime-evidence/cli-filer.txt
docs/task01-runtime-evidence/cli-master.txt
docs/task01-runtime-evidence/cli-s3.txt
docs/task01-runtime-evidence/cli-volume.txt
docs/task01-runtime-evidence/current-services.json
docs/task01-runtime-evidence/initial-services.json
docs/task01-runtime-evidence/python-pip-check.txt
docs/task01-runtime-evidence/python-version.txt
docs/task01-runtime-evidence/seaweed-image-digest.txt
docs/task01-runtime-evidence/source-integrity.json
docs/task01-runtime-evidence/volume-status.json
```

Ngoài manifest, luôn loại `.env/.env.local`, `.local/`, credentials/keys/auth state, backups/dumps/media/volumes, `.python/`, `.venv/`, node_modules/`.next`, caches/logs/test outputs. Không force-add. Source backup `.bak` lịch sử không hiện diện trong candidate. `docs/task01-evidence/README.md` giữ làm context; raw outputs bị loại là bằng chứng lịch sử chưa được publish review, không phải dependency ứng dụng/CI.

Candidate export `.python/p11-acceptance-candidate` có **648 source/artifact files** (không tính bytecode/cache sinh bởi kiểm thử): 645 source files INCLUDE, bản `.vscode/settings.json` từ HEAD (giữ local modification ngoài candidate), hai derived artifacts. Không có private env/dependency folders. Đã chạy Django system/migration checks trên đúng export này: PASS, 0 issues/0 changes; package/migration dependencies đầy đủ. Không tạo Git repo/index/commit giả để gọi đây là checkout remote. Commit SHA/tree thực chỉ có sau khi người dùng curate/commit; chưa có remote acceptance.

### 11.4 Acceptance matrix và trạng thái bàn giao

| Gate | Kết quả lượt Final Acceptance |
| --- | --- |
| Environment/target/live guards + repository safety units | **LOCAL PASS 30/30**, 0 skip, 27,461s. Có ca âm labels/resource scope trước setup/DB/S3/SMTP/temp media/write; giữ nguyên 27 bài trước và mở rộng assertions. |
| Related PostgreSQL regression: security, storage adapter, loopback HTTP helper | **LOCAL PASS 48/48**, 0 skip, 0 failures/errors, 1,119s. |
| Feature-enabled fixtures (routing/qualification/telemetry/layouts/presigned download) | **LOCAL PASS 72/72**, 0 skip, 88,510s. |
| Full Django default runner | **LOCAL PASS** 614 discovered = 595 thực thi + 19 provider SKIP, 0 failures / 0 errors, 1170,831s; lượt đầu trước chỉnh nhánh teardown không tạo DB. |
| Runner không có database-using tests | **LOCAL PASS 2/2**, 0 skip, 0,045s trên candidate; không CREATE/DROP DB. Teardown kiểm control target khi `old_config` rỗng; CI thêm cùng gate. |
| Full Django candidate code cuối | **LOCAL PASS**: 614 discovered = **595 thực thi + 19 provider SKIP**, **0 failures / 0 errors**, **1054,663s**; sau sửa lifecycle no-DB, source runner/settings/guards/workflow khớp working tree bàn giao. |
| Candidate export system check / migration consistency | **LOCAL PASS**, 0 issues, 0 changes; không migrate serving hoặc control DB. |
| Working-tree / index security scans | **LOCAL PASS độc lập**: working tree 662 text / 5 binary chưa scan, index 419 text / 1 binary chưa scan, 0 findings / blocked. History raw scan riêng vẫn FAIL 4 findings / 29 commits, được phân loại ở §11.2. |
| Frontend | **NOT RERUN / không áp dụng thay đổi lượt này**: đối chiếu 275 frontend source files giữ nguyên hash, không đổi config/runtime/dependency/UI. Kết quả frontend §10 là evidence lượt trước, không cộng làm PASS mới. |
| Git candidate review | **READY FOR USER REVIEW / NOT STAGED**: paths/dependencies reviewed, 674 inventory rows + 2 artifacts; exclusions và seed fix đã có quyết định. **NOT READY TO PUBLISH** tới khi operator credential disposition và người dùng curate đúng paths; chưa stage candidate. |
| GitHub Actions remote | **NOT RUN trên candidate**: chưa commit/push, workflow/candidate chưa thuộc SHA remote có thể nghiệm thu. Không lấy run cũ thay cho candidate. |
| History security | `.bak`: informational disposition đã rõ; hai credential materials: **OPERATOR REVIEW REQUIRED**, có kế hoạch xử lý, chưa chứng nhận retire/unused. Không rewrite/rotate. |

Lệnh và fresh logs: `%TEMP%/bluedrive-p11-acceptance-{guards,related,enabled,full,candidate,no-database,candidate-full}-20261116.log`; artifacts/caches/export/snapshot trong `.python/` ignored. Git HEAD/index và những thay đổi có sẵn được kiểm lại trước bàn giao. Lượt này sửa 12 file có sẵn (runner, guard tests, workflow và docs/artifacts), không thêm source module/dependency mới; các file khác giữ nguyên. Lần scan trung gian bắt một URL userinfo giả khi test fixture được chép vào patch (patch không có fixture exemption); đã tách ca âm username-only/password-only, giữ coverage cả hai trường và không nới scanner. Scan mới PASS. Patch P1.1 hiện có được cập nhật cumulative theo baseline P1, kiểm trên bản sao; không tạo tài liệu trùng hoặc apply/reset source của người dùng.

Rollback source: dùng đúng cumulative P1.1 patch sau review để quay toàn P1.1, hoặc đối chiếu acceptance-before snapshot để chỉ hoàn nguyên delta lượt cuối; không reverse toàn bộ diff với HEAD và không bỏ staged seed fix. Rollback live guard sẽ mở lại rủi ro chọn nhầm labels/tài nguyên. Không có runtime rollout, migration dữ liệu, rotation, volume cleanup hoặc P2 nào cần rollback.

**Chưa đề xuất chuyển P2.** Điều kiện: local gates cuối PASS; người dùng review/curate candidate đúng groups/paths; operator ghi kết quả retire/unused/risk acceptance cho demo password và signing key, quyết định policy history trước publish; sau đó remote repository-safety/backend/frontend jobs phải **PASS trên đúng commit SHA**, ghi URL/run/SHA vào báo cáo. Thiếu một gate vẫn để acceptance mở; không tự commit/push/deploy để đóng gate.

Kết thúc lượt Final Acceptance: **LOCAL PASS** cho các gate áp dụng ở §11.4. Trước bàn giao đã kiểm lại marker/role/port của control service và **0 DB test UUID còn lại**, dừng riêng PostgreSQL `bluedrive-tests-postgres-1`; không xóa volumes hoặc cleanup dữ liệu phục vụ. HEAD/index không đổi, **12 files sửa / 655 files có sẵn giữ nguyên hash** trong lượt này; 9 deletions cũ giữ nguyên. Candidate **READY FOR USER REVIEW, NOT STAGED / NOT READY TO PUBLISH**, remote CI **NOT RUN**, hai credential materials vẫn **OPERATOR REVIEW REQUIRED**. Không commit/push/deploy/P2. Có thể bổ sung workflow live-label/resource allowlist → history disposition → curated manifest → candidate regression vào project skill hiện có khi lặp lại; chưa sửa/tạo skill mới.

## 12. P1 Final Closure — Security Disposition, Git Integration & Remote CI

**Trạng thái quyết định mới nhất:** xem **§12.8**. Bằng chứng và quyết định giữ publish tại §12.1–§12.7 là lịch sử của các lượt trước; quyền tự chủ mới cho phép đánh giá disposition và tích hợp candidate sau security gates. Chưa đánh FINAL ACCEPTED trước khi ba remote jobs đạt cùng commit SHA.

Ngày **16/11/2026**, Asia/Bangkok. Phạm vi **chỉ môi trường local được kiểm tra**. Rotation được duyệt ở §12.6; dependency recovery/runtime verification ở §12.7. Signing key đã **RETIRED — VERIFIED LOCAL RUNTIME**. Operator vẫn **giữ publish BLOCKED để review Git history thêm**; login serving bằng tài khoản thật chưa được cấp phép và remote CI NOT RUN. **PENDING ACCEPTANCE**, không phải FINAL ACCEPTED. Kết quả từng lượt được ghi riêng, không lấy số kiểm thử cũ làm kết quả mới.

### 12.1 Trạng thái đầu lượt và phạm vi được thực hiện

- HEAD: `d968ebffa0d17f4fce81c2b2f56af5021e60e070`; branch có sẵn `feature/storage-control-center-s4-20261109`, không phải main. Remote cấu hình đã đối chiếu: `https://github.com/binos2303/BlueDrive.git` (không in userinfo/token nếu có).
- Đối chiếu **674/674 rows** manifest với working tree: 0 mismatch SHA-256/trạng thái ADD/MODIFY/DELETE; source snapshot 667 files public/không ignored, 406 status entries khi lấy cả untracked paths. Không giả repository sạch.
- Index chỉ có `backend/dashboard/management/commands/seed_demo.py` staged từ P1; blob khớp working tree và bản security fix đã review. Index listing digest giữ `fec2be796e888a1d10eaf3632d3a10557b2706287038dc68537ed4546d3a83c9`. Các thay đổi baseline/pre-P0 và 9 deletion cũ được giữ nguyên.
- Snapshot public source/status ở `.python/p1-closure-before*` ignored; không copy private env, key, media/DB/volume/auth state. Không áp patch P1/P1.1 lên HEAD, không reset/stash/ghi đè công việc có sẵn.
- Yêu cầu closure cho phép đọc cấu hình cần thiết và DB an toàn để disposition; audit này là tác vụ có mục tiêu riêng, không thay scanner/CI mặc định thành công cụ đọc private env. Chưa thay key/credential, account/session, fallback hoặc restart dịch vụ phục vụ.

### 12.2 Security Disposition có bằng chứng runtime chỉ đọc

Phương pháp: lấy literal lịch sử trong memory từ đúng blobs, không thực thi seed. Cấu hình `backend/.env` được parse trong memory theo ưu tiên dotenv `override=False` cùng environment của process audit, không dump env. Kết nối đúng DB ứng dụng local từ cấu hình, ghim địa chỉ TCP loopback, kiểm database/role khớp, `transaction_read_only=on`, `default_transaction_read_only=on`, transaction REPEATABLE READ và statement timeout 5s. Không migrate, seed, ORM/save hoặc authenticate/login.

Auth-table audit chỉ trả boolean seed-candidate/active và encoded password vào memory, dùng `check_password(..., setter=None)` để không nâng hash hoặc ghi DB. Chỉ xuất tổng hợp; không in password, encoded hash, username/email/ID. Session audit chỉ `TimestampSigner.unsign` với salt của SessionStore, không deserialize payload hoặc đọc identity, không sửa/xóa session. Audit kết thúc rollback transaction chỉ đọc.

| Finding | Evidence mới / hiện tại | Risk | Disposition | Action Required |
| --- | --- | --- | --- | --- |
| Seed blob `8e71f6c8befc`, dòng 25 | `DEFAULT_PASSWORD` → argparse default → `user.set_password` cho user mới; 10 tên ứng viên được suy ra trong memory. Trong **5** auth rows hiện tại: **0** seed-candidate accounts, **0** password matches, **0** active matches, **0** hash không thể kiểm tra. | Từng là credential bootstrap có thể dùng thật; exposed material vẫn trong history. Không có evidence đang dùng trong runtime local được phép kiểm tra. | **VERIFIED NOT CURRENTLY USED — checked local scope**. Phạm vi chỉ local đã được người phụ trách closure xác nhận. Không gọi đây là bảo đảm cho deployment giả định ngoài scope. | Không có account match để rotate/thu hồi trong DB này. Giữ source fix bỏ default/in password và không dùng lại password lịch sử. Không cần rewrite chỉ để xử lý một credential không còn được dùng trong scope đã xác minh. |
| Seed blob `3e4b401b8079`, dòng 24 | Cùng credential material với blob trên theo so sánh memory; cùng kết quả 0/5 hiện tại. Command chỉ set password khi tạo user mới, không tự đổi password của user có sẵn. | Không phải credential khác cần rotation lần hai. | **VERIFIED NOT CURRENTLY USED — checked local scope**, cùng disposition trên. | Giữ bản seed fix staged trong candidate. Không chạy lại seed/reset account để chữa finding. |
| Signing key blob `2e55a20ba2d1`, `securedrive/settings.py:23` | Sau recovery §12.7, chính process phục vụ dùng key mới, fallback rỗng, từ chối old signatures và xác minh new signatures; PID khớp listener loopback 8000. **8/8** old-session HTTP requests bị từ chối auth, 30 session rows giữ nguyên. | Exposed material vẫn trong history; retirement local không chứng nhận deployment ngoài scope hoặc login thật chưa được phép. | **RETIRED — VERIFIED LOCAL RUNTIME**. Publish vẫn **BLOCKED theo quyết định operator review history thêm**. | Giữ key mới, không fallback/rewrite; đóng auth serving/candidate/remote CI gates khi đủ quyền và bằng chứng. Không dùng password lịch sử hoặc đổi account/data. |
| Backup-source blob `257ee385e76e` | Blob/HEAD evidence không đổi: `AdminFilesAPITests(TestCase)`, fixture `setUp`, hai password fixture khác demo default, không operational top-level calls/token/private-key/URL-password finding. File không hiện diện trong HEAD/index/current candidate. | Backup name policy finding, không phải credential runtime hoặc DB dump theo evidence blob này. Không miễn trừ mọi `.bak`. | **INFORMATIONAL / NO SECRET REMEDIATION**, giữ kết luận P1.1. | Không đưa backup vào commit; không cần rotate hoặc rewrite vì riêng blob source fixture này. Scanner private-artifact policy giữ nguyên. |

**Giới hạn chính xác:** audit/probe độc lập tại §12.6 chưa đủ xác nhận serving; §12.7 đã bổ sung active attestation và HTTP trong chính backend loopback. Không dump process environment hoặc thử đăng nhập bằng credential lịch sử. Chưa có tài khoản thật được phép để nghiệm thu serving login/logout; fixture tests không thay gate này. Publish vẫn bị chặn theo quyết định history review của operator.

**Remote exposure:** evidence §11.2 vẫn có hiệu lực: commit `664ffb8de2d279776812a9b548099dc02a2dda2b` đã được đọc qua GitHub; graph cho thấy seed-old và settings commit là ancestor. Hai seed blobs có cùng material. Không coi history này là chắc chắn chỉ local hoặc dùng source/index PASS để phủ nhận exposure. Không rewrite, force-push, thay visibility hoặc mở rộng lịch sử lên remote.

**Kế hoạch operator đã duyệt — bằng chứng rotation tại §12.6 và dependency/runtime verification tại §12.7:**

1. Giữ gate branch/commit/push đóng theo quyết định hiện tại. Operator bảo toàn private config bằng cơ chế backup có quyền truy cập phù hợp; không đưa backup/key vào Git hay báo cáo.
2. Chọn signing key mới từ nguồn ngẫu nhiên mật mã và thay đúng `SECRET_KEY` trong cấu hình có hiệu lực, kể cả nguồn inject nếu có. Không đổi `SECUREDRIVE_AES_KEY`, storage credential/endpoint, DB credential hoặc flags để xử lý signing key.
3. Không giữ exposed key trong `SECRET_KEY_FALLBACKS`. Không cần xóa DB session rows để chứng minh retirement; operator chấp nhận/điều phối việc signed sessions/tokens cũ có thể mất hiệu lực và người dùng cần xác thực lại. Không tự gọi logout/flush/revoke hoặc sửa data.
4. Operator kích hoạt/reload chỉ backend đã được duyệt, rồi xác nhận effective process dùng config mới. Không restart Filer/SeaweedFS hoặc dịch vụ khác như một phần việc này.
5. Audit lại chỉ đọc: config/current verifier không dùng key lịch sử; không có fallback chứa nó; verifier dùng current key/fallbacks phải từ chối old-signed records. **Old-key verifier vẫn có thể xác minh chữ ký lưu trong DB sau rotation; con số đó không phải tiêu chí key còn active.** Phải xem current-verifier acceptance và effective config/reload evidence.
6. Chỉ khi signing-key disposition đóng mới mở bước Git/remote CI đã được phép có điều kiện. History rewrite không thay thế retirement; nếu policy đòi scrub thì cần phạm vi riêng, không làm trong closure này.

Artifact audit local: `.python/p1_closure_security_audit.py` và `.python/p1-closure-security-sanitized.json`, ignored, chỉ chứa code đọc có kiểm soát và boolean/count output. Không copy key/hash/identity vào artifact. Không force-add audit artifact hoặc dùng nó trong CI mặc định, vì CI không được đọc DB/config phục vụ. Kế hoạch ảnh hưởng/key separation đối chiếu [Django SECRET_KEY guidance](https://docs.djangoproject.com/en/5.2/ref/settings/#secret-key) và [GitHub sensitive-data remediation](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).

### 12.3 Git candidate và integration đã chuẩn bị, chưa mở gate

Đã thực thi manifest review với source hiện tại: hash 674 rows, Git actions, INCLUDE/EXCLUDE, seed staged fix, dependencies/migrations/frontend assets và 9 deletions có sẵn đều khớp. Vẫn **384 delta paths + 2 derived artifact paths**, 270 KEEP_HEAD và 20 EXCLUDE ở §11.3. Exclusions được giữ nguyên; không force-add private env, credentials/session state/data/volumes/dependencies/cache/log hoặc raw outputs.

Tạo source export sạch `.python/p1-closure-candidate`: 648 source/artifact files theo manifest, lấy `.vscode/settings.json` từ HEAD để giữ local editor delta ngoài candidate, không có `.env/.env.local`, `.venv` hoặc node_modules lúc bắt đầu. Candidate này đã được dùng cho các kiểm thử closure bên dưới; không tạo Git repo/index giả trong export, không áp cumulative patch vào source.

Kế hoạch commit đã có **danh sách path cụ thể** ở `.python/p1-closure-commit-plan.json`, chưa stage/commit:

| Commit theo trách nhiệm | Nhóm | Paths |
| --- | --- | ---: |
| Backend và infrastructure baseline | G0 + G1 + G4, có seed security fix | 84 |
| Frontend và shared UI baseline | G2, gồm assets/Poppins/config/callers | 139 |
| Verification/CI và test isolation | G3, có apps tests/test settings/runner/PostgreSQL marker | 81 |
| Documentation và ADR alignment | G5 + hai derived artifacts | 82 |

Đây là kế hoạch tích hợp nguyên candidate phụ thuộc nhau, không chỉ commit CI và không chia máy móc làm thiếu module/migration/frontend dependency. Chỉ stage whitelisted paths bằng thao tác có pathspec tường minh sau gate, không `git add .`, `git add -A` toàn repo hoặc `git add -f`. Các path lạ/sha đổi sẽ phải review lại trước stage.

**Git actual:** chưa tạo acceptance branch, current branch/HEAD/index giữ nguyên. Runtime signing key đã được xác minh ở §12.7, nhưng operator **giữ publish BLOCKED để review history thêm**; không tạo branch/stage/commit/push/PR hoặc remote run khi gate đóng. Không thử quyền push, overwrite/delete branch hoặc amend history có sẵn.

### 12.4 Kiểm thử closure mới và acceptance gates

Các lệnh dùng `.venv` Python 3.12.10 hiện có, không tạo thêm venv. PostgreSQL chỉ là service test tmpfs có marker, mỗi suite UUID riêng; không migration serving/control DB, không live provider. Frontend được cài sạch trong export từ lockfile, dùng cache đã kiểm tra integrity/offline và cùng `--ignore-scripts` như CI, không cài dependency ngoài dự án.

| Gate | Kết quả lượt closure |
| --- | --- |
| Candidate source/Git action/manifest consistency | **PASS** 674 rows / 0 mismatch; 20 EXCLUDE giữ ngoài candidate; seed fix staged đúng. |
| Django system check | **PASS** 0 issues. |
| Migration consistency | **PASS** 0 changes, không apply migration DB phục vụ. |
| Environment/target/live + repository guard units | **PASS 30/30**, 0 skip, 32,218s. |
| Full Django/PostgreSQL candidate | **PASS** 614 discovered = **595 thực thi + 19 provider SKIP**, **0 failures / 0 errors**, **880,971s**. |
| Feature-enabled fixtures | **PASS 72/72**, 0 skip, 119,381s. |
| Runner lifecycle không có database-using tests | **PASS 2/2**, 0 skip, **0,010s**, không CREATE/DROP DB. |
| Dependency compatibility | **PASS** pip check; không đổi requirements/lockfiles/package đang cài. |
| Frontend clean install | **PASS** npm ci, 383 packages, cache offline integrity, không serving env. |
| Frontend lint / Next typegen / TypeScript | **PASS** tất cả, exit 0. |
| Node unit tests | **PASS 159/159**, 0 fail/skip, 39 test files, 2855,4085ms. |
| Next production build | **PASS**, 40/40 static pages; Poppins local, không sửa UI để né build. |
| Working-tree safety / staged-index safety | **PASS độc lập**: working tree 662 text/5 binary chưa scan, index 419 text/1 binary chưa scan, 0 findings/blocked; sẽ chốt lại cùng artifacts. |
| Git diff / cached diff whitespace | **PASS**, manifest Git actions đều khớp. |
| Workflow local validation | **PASS** 3 jobs, action SHA pins, read-only contents/checkout, CI PG target/marker/no-DB gate. Không đổi workflow để bỏ test. |
| Remote repository-safety / backend / frontend jobs | **NOT RUN** cả ba: publish gate đang bị chặn theo Security Disposition, không phải kết quả CI FAIL hoặc thiếu quyền đã kiểm chứng. |
| Runtime data protection | Chỉ đọc auth/session bằng transaction READ ONLY; không login/ORM/save/key change/session revocation, không serving/Filer migration hoặc volume cleanup. |

Raw history scan vẫn có 4 finding blobs như §11; disposition mới đóng hai seed rows trong scope local và xác nhận `.bak` informational, **không** biến scanner raw FAIL thành PASS. Provider tests default giữ **19 SKIP** và không cộng thành PASS. Node module-type và npm eslint deprecation warnings được ghi nhận, không nâng package hoặc bỏ test để làm mất warning.

Fresh logs chỉ giữ local: `%TEMP%/bluedrive-p1-closure-{guards,check,migrations,full,no-db,enabled,frontend}-20261116.log`. Snapshot/source export/npm cache/audit/commit-plan artifacts trong `.python/` ignored, không force-add. Những thay đổi source closure chỉ là cập nhật báo cáo hiện có và derived manifest/patch sau khi chốt evidence; chưa thay business/frontend/CI code hoặc dependency trong lượt closure.

### 12.5 Final status và điều kiện tiếp tục

| Trường bàn giao | Giá trị hiện tại |
| --- | --- |
| Acceptance | **FINAL ACCEPTED — development baseline**, 17/11/2026; giới hạn tại §12.8 |
| Current branch | `refactor/p1-baseline-acceptance` |
| Integration base HEAD | `d968ebffa0d17f4fce81c2b2f56af5021e60e070` |
| Validated implementation commit SHA | `40d05a5593b84e20858f04562e878178208af621` |
| Draft PR URL | [PR #1](https://github.com/binos2303/BlueDrive/pull/1), không merge/deploy |
| GitHub Actions run URL | [Push run 43942204201](https://github.com/binos2303/BlueDrive/actions/runs/43942204201), [PR run 43942215088](https://github.com/binos2303/BlueDrive/actions/runs/43942215088) |
| repository-safety / backend / frontend remote results | **PASS / PASS / PASS** trên cùng SHA implementation nêu trên |
| Demo password | **VERIFIED NOT CURRENTLY USED** trong runtime local đã xác nhận |
| Django signing key | **RETIRED — VERIFIED LOCAL RUNTIME**, xem §12.7 |
| Runtime configuration | **VERIFIED** trong process phục vụ loopback: key/fallback/signature, PID/listener và old-session HTTP denial |
| `.bak` | **INFORMATIONAL / NO SECRET REMEDIATION** |
| Serving positive login/logout | **NOT VERIFIED — accepted development limitation**, không dùng account thật |
| P2 readiness | **READY FOR DEVELOPMENT** theo quyền mới; không tự migrate serving hoặc provision storage |

Quyền tự chủ mới và disposition tại §12.8 thay gate chờ operator của lượt trước. Runtime retirement được xác minh, candidate đã tích hợp, ba remote jobs PASS trên cùng implementation SHA. Positive serving login/logout được chấp nhận là giới hạn development có ghi nhận, không đổi thành PASS. P1 đủ điều kiện bắt đầu P2 development; tiếp tục cấm rewrite/force-push shared history, dữ liệu/migration serving chưa duyệt, merge và deploy.

Kết thúc lượt closure **trước rotation**: kiểm thử ở §12.4 đã **PASS**; full Django **595 PASS / 19 SKIP**, frontend **159 PASS**, guards **30 PASS**, enabled fixtures **72 PASS**, no-DB lifecycle **2 PASS**. Đã xác nhận đúng marker/role/port và **0 test DB UUID còn lại**, rồi dừng riêng test service; không xóa volumes hoặc cleanup dữ liệu thật. Source closure khi đó chỉ sửa **3 files hiện có**: báo cáo này và hai derived manifest/patch; **664 public files còn lại giữ nguyên hash**. Đây là evidence lịch sử của lượt closure, không phải kết quả chạy lại sau rotation; kết quả mới ở §12.6. HEAD/branch/index giữ nguyên, seed fix staged được bảo toàn; chưa có branch/commit/PR/push hoặc remote CI mới. Chưa đủ điều kiện P2.

### 12.6 Local signing-key rotation đã duyệt — bằng chứng tại thời điểm rotation

Operator chấp thuận tường minh việc thay riêng Django `SECRET_KEY` local, chấp nhận **8 session hiện tại và token ký bằng key cũ có thể mất hiệu lực**, cần đăng nhập lại. Quyền này không mở rộng sang deployment khác, hạ tầng, AES/storage/DB credentials hoặc dữ liệu. Không tự khôi phục key đã lộ nếu gặp lỗi.

**Preflight mới:** nguồn key là một binding trong `backend/.env`, dotenv `override=False`; không có `SECRET_KEY` override ở parent process hoặc Windows user/machine environment, không có `DJANGO_SETTINGS_MODULE` override. Source không khai báo fallback, framework default rỗng. Không quan sát Python executable/backend/worker hoặc listener 8000. PostgreSQL ứng dụng local truy cập được; PostgreSQL test 55432 và S3 8333 không truy cập TCP được. Docker engine named pipe không khả dụng. Không khởi động Docker hoặc restart SeaweedFS/Filer/PostgreSQL. Nạp settings với profile mặc định `DEBUG=False` bị HTTPS guard chặn vì public storage endpoint HTTP local; không sửa `.env` để né guard.

**Bảo toàn và thay cấu hình:** tạo thư mục `.python/p1-key-retirement-private/` trên NTFS, tắt inheritance và chỉ cấp FullControl cho current operator, SYSTEM, Administrators. Xác minh đúng ba Allow rules, không rule lạ, trước khi copy private config. Backup `.env.before` được ghi độc quyền, flush/fsync và đối chiếu byte với bản gốc; nằm ngoài Git/manifest, không in nội dung. Key mới sinh bằng `secrets.token_urlsafe(64)` từ nguồn ngẫu nhiên mật mã, không truyền qua argv/history/log. Dùng Windows `ReplaceFileW` với flags 0, không bỏ qua lỗi ACL; kiểm lại private config không có broad Allow rules. Chỉ giá trị `SECRET_KEY` đổi; mọi byte khác, comment, newline và field khác giữ nguyên. Không giữ key lịch sử trong fallback. Nguồn tham chiếu: [Windows ReplaceFileW](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-replacefilew), [Django SECRET_KEY](https://docs.djangoproject.com/en/5.2/ref/settings/#secret-key).

**Process kiểm chứng:** Django process mới, độc lập, nạp `securedrive.settings` và key trực tiếp từ private config, không inject `SECRET_KEY`. Chỉ process probe dùng `DEBUG=true` theo HTTP local profile đã duyệt; không đổi private DEBUG/flags hoặc bỏ HTTPS guard của cấu hình deployed. Chặn DB connection/network trong crypto probe; không bind cổng, gửi email, ghi media hoặc tạo account/session. Logging/traceback được giữ trong memory và không xuất dữ liệu bí mật.

| Kiểm chứng mới sau rotation | Kết quả / phạm vi |
| --- | --- |
| Private backup ACL, integrity, chỉ đổi signing-key value | **PASS**; ba trusted Allow rules, không broad Allow trên config hiện hành. |
| Django crypto probe | **PASS 19/19**, không skip: effective key mới, fallback rỗng, chữ ký thường/timestamp cũ bị từ chối và chữ ký mới hợp lệ; session encode/decode, auth hash, password-check fixture chưa save, password-reset/admin-invitation token và CSRF missing/mismatch denial + valid acceptance. Không gọi đây là relogin API acceptance. |
| Session audit chỉ đọc | **PASS**: **30 → 30** session rows tổng, **8** chưa hết hạn; old-key verifier vẫn xác minh 8 stored signatures, current-key verifier chấp nhận **0/8**. Không deserialize session payload hoặc xuất identity; không xóa/revoke/logout. |
| DB/data preservation | **PASS**: đọc đúng database/role local, transaction/default read-only, REPEATABLE READ, timeout 5s; đối chiếu nội dung bounded **39 bảng** auth/session, files/folders, accounts, infrastructure trước/sau, tất cả giữ nguyên. Digest chỉ dùng trong memory, không đưa vào báo cáo. Không migration/save/seed hoặc ghi DB. |
| AES/storage/DB configuration preservation | **PASS**: mọi field ngoài SECRET_KEY giữ nguyên; AES reader trong process probe trả đúng key từ backup, không in key. Không đổi storage bindings, endpoint/credential hoặc flags. Không chứng nhận provider I/O khi service chưa sẵn sàng. |
| Demo password | **VERIFIED NOT CURRENTLY USED**: audit mới 5 auth rows, 0 exposed-password matches, 0 active matches, 0 unverifiable hashes; không thay account/password. |
| Environment/target/live và repository guard units | **PASS 30/30**, 0 skip, 19.294s: `python -B -X utf8 -m unittest discover -s backend/tools -p 'test_*.py'` bằng `.venv` hiện có. |
| Loopback HTTP guard units | **PASS 2/2**, 0 skip, 0.022s; fixture server loopback cổng tạm, không phải backend serving. |
| Working-tree / index security scan | **PASS độc lập**: `check_repository_safety.py` working tree 662 text/5 binary không scan; `--staged` index 419 text/1 binary không scan; 0 findings/blocked. Chạy lại sau khi chốt report/artifacts. |
| Git history scan | **FAIL — 4 known findings**, không phải finding mới: `check_repository_safety.py --history HEAD`, 29 commits/740 unique blobs, 0 blocked; disposition theo §12.2 và hàng security bên dưới. Không sửa scanner để gọi history sạch. |
| Dependency compatibility | **PASS** `pip check`, không thêm/nâng package. |
| Django system check | **PASS**, 0 issues với isolated test settings. |
| Migration consistency | `makemigrations --check --dry-run --settings securedrive.test_settings` báo **No changes detected**, exit 0; kiểm lịch sử migration trên test DB **BLOCKED**, có connection-timeout warning. Không coi toàn bộ migration consistency PASS khi PostgreSQL test chưa sẵn sàng; không apply migration. |
| Serving process effective configuration | **BLOCKED**: dependency S3 local thiếu; không khởi chạy backend 8000 theo điều kiện đã duyệt. Process probe PASS không thay thế activation/serving evidence. |
| Login lại, API session/auth/CSRF/token flow thực tế | **BLOCKED**: chưa có serving backend; chỉ crypto/CSRF component checks phía trên đã PASS. |
| Full Django / enabled-fixture PostgreSQL regression | **BLOCKED**: test PostgreSQL/Docker chưa khả dụng; không mượn serving DB, không khởi động hạ tầng, không lấy số §12.4 thành kết quả mới. Giữ 19 provider SKIP của baseline tách khỏi PASS. |
| Frontend | **NOT RUN** trong lượt rotation: không sửa frontend/build/dependency. Các kết quả §12.4 là lịch sử, không gắn nhãn kiểm thử mới. |
| GitHub Actions | **NOT RUN**; publish gate còn đóng, không có commit SHA/PR/run mới. |

Rà soát callers: Django DB session signatures và session auth hashes, `default_token_generator` dùng cho platform administrator invitation/password reset bị ảnh hưởng khi bỏ old key. Telemetry WebSocket/session verifier cũng phụ thuộc auth hash hiện hành. Workspace invite dùng token ngẫu nhiên/hash riêng; AES legacy và S3 signing dùng key/credentials độc lập. Password hashes không dựa vào SECRET_KEY nên rotation không tự đổi mật khẩu. Không thử credential lịch sử hoặc gửi invitation/email thật.

**Security disposition tại cuối lượt rotation, trước dependency recovery:** demo password **VERIFIED NOT CURRENTLY USED — checked local scope**; signing key **CONFIG ROTATED / RETIREMENT ACCEPTANCE BLOCKED**; runtime configuration **VERIFIED trong process độc lập / serving BLOCKED**. Hai seed history findings có cùng material, giữ source fix staged; `.bak` source fixture vẫn INFORMATIONAL. Known history findings không biến mất và không gọi history scan PASS. Không rewrite history; không publish trước khi effective serving/relogin gates đóng. Khi dependency local được operator làm sẵn, tiếp tục đúng phạm vi backend đã duyệt, xác minh current process rồi mới mở bước Git và ba remote jobs trên cùng SHA.

**Khôi phục:** backup giữ private và không tự xóa; nếu cần khôi phục field không phải signing key, lấy từ backup trong quyền operator và giữ một signing key an toàn. Không tự phục hồi exposed key hoặc thêm nó vào fallback. Không có process serving mới cần dừng trong lượt này. Local helper `.python/p1_rotate_local_signing_key.py`, sanitized evidence `.python/p1-key-retirement-sanitized.json` và audit artifact đều ignored, không thuộc candidate/CI. Helper rotation từ chối chạy lại khi backup đã tồn tại hoặc current key không còn khớp lịch sử.

**Git handoff:** chỉ báo cáo hiện có và hai derived manifest/patch được cập nhật; không sửa nghiệp vụ/frontend/workflow hoặc dependency. HEAD/branch/index và seed fix staged giữ nguyên; 20 EXCLUDE được bảo toàn. Chưa tạo acceptance branch, stage thêm, commit, push, Draft PR hoặc Actions run. **PENDING ACCEPTANCE / P2 NOT READY** cho đến khi serving/security gates, candidate review và remote CI trên đúng commit hoàn tất.

### 12.7 Dependency Recovery & Runtime Verification — kết quả tiếp nối

Ngày **16/11/2026**, Asia/Bangkok. Operator duyệt mở Docker Desktop ở nền và khôi phục riêng Platform hiện hữu sau kiểm kê project/mount. Operator **chưa chỉ định tài khoản test serving**, yêu cầu không tìm/sử dụng credentials user thật/Platform Admin/Organization Admin, chuyển auth smoke sang fixture DB độc lập. Operator chọn **giữ publish BLOCKED để review history thêm**. Không rotation lại, không thay private key/config, account hoặc dữ liệu phục vụ.

#### Dependency recovery đã xác minh

| Thành phần | Kết quả / phân loại |
| --- | --- |
| Docker Desktop / Engine | **PASS**: trước recovery không có process Desktop/Engine pipe, `autoStart=false`; mở executable đã có với cửa sổ ẩn theo approval. Engine hoạt động, không phải lỗi credentials/network hoặc bằng chứng hỏng container/volume. Không reset Docker, recreate, pull hoặc upgrade. |
| Application PostgreSQL | **PASS**: Windows service PostgreSQL 18 và cổng 5432 giữ nguyên; kết nối đúng app DB/role bằng private config, transaction read-only. Không restart hoặc migrate. |
| Platform SeaweedFS | **PASS health**, **8 container hiện hữu** (Master, Volume 1–4, Filer, S3, Filer PostgreSQL) tự khôi phục theo restart policy. Đã inspect project/service/image/mount, health đều healthy. Volume 4 có sẵn, tự resume; không chủ động start/reconfigure nó. Không cấp Enterprise provisioning. |
| Platform ports / credentials | Master loopback 9333 `/cluster/healthz` **200**, S3 loopback 8333 unauthenticated **403** đúng bucket-private policy. Binding `primary` là Platform/ready/verified, không error code, routing flag ON đã có sẵn; signed **HEAD bucket 200** bằng đúng credential aliases của revision, chỉ đọc. Không chạy object PUT/DELETE hoặc provider qualification. |
| Filer PostgreSQL / Volume / Filer | Health và mount/network của container hiện hữu đã kiểm; Filer PostgreSQL 17 nằm trong Docker storage network, khác native application DB và test PostgreSQL. Không sửa DB/config/mount hoặc dữ liệu. Health không thay provider I/O acceptance. |
| Global legacy endpoint | Cấu hình global vẫn trỏ loopback **9000**, TCP không sẵn sàng; routing hiện hành dùng binding SeaweedFS **8333** đã xác minh. **Không đổi endpoint/binding hoặc khởi động MinIO** để né lỗi. Legacy file flows phụ thuộc 9000 chưa được nghiệm thu, ngoài scope kiểm chứng key/auth này. |
| PostgreSQL test | **PASS**: start đúng container test hiện hữu, image PostgreSQL 18.6 ghim digest, tmpfs `/var/lib/postgresql`, một init SQL bind read-only, host `127.0.0.1:55432`. Marker/control DB `bluedrive_test_control`, role `bluedrive_test`, server port 5432 khớp contract trước lifecycle UUID; 0 DB UUID trước suite. Không mượn DB phục vụ. |
| Enterprise / MinIO | **Không thay đổi**: 5 Enterprise containers và 1 MinIO container vẫn exited; không chủ động khởi động, xóa hoặc provision. |

Không có bằng chứng volume/container hỏng. Lỗi ban đầu là Desktop/Engine chưa chạy, không phải đã xác minh sai credential. Docker inspect chỉ lấy project/service/image/state/health/mount/port; không dump Env hoặc health logs. Một lần Go-template quoting Windows bị từ chối trước thao tác; chuyển sang argv Python, không sửa container để chữa công cụ kiểm kê.

#### Serving signing-key retirement và HTTP smoke

Khởi chạy wrapper local qua `.venv` hiện có, **PID 23616**, bind **127.0.0.1:8000**, không autoreload. Chỉ process dùng `DEBUG=true` theo HTTP local profile đã duyệt; không sửa `.env`, production HTTPS guard, feature flags hoặc key. Lần launch đầu không duy trì được process sau lệnh; không tính PASS từ attestation cũ, đã xác nhận không còn process/listener đó trước lần chạy được giám sát. PID hiện hành được kiểm lại khớp listener sau HTTP smoke.

Trong **chính process phục vụ**, 19 crypto preflight checks và **4 active runtime checks sau bind** đều PASS: effective key khớp private key mới và khác exposed key, fallback rỗng, old signature bị từ chối, new signature hợp lệ. Django system check 0 errors. Không thêm endpoint debug/auth bypass; attestation chỉ boolean/count/PID, không có key/token. Runtime logging/HTTP bodies/cookies không đưa vào terminal hoặc artifact.

| Serving HTTP test | Kết quả |
| --- | --- |
| HTTP readiness / CSRF bootstrap | **PASS** `GET /accounts/api/csrf/` 200, nhận token/cookie chỉ trong memory. Đây là basic HTTP readiness, không chứng nhận mọi nghiệp vụ/file I/O. |
| Anonymous account / CSRF denial | **PASS** account GET bị từ chối; login POST thiếu CSRF hoặc token sai đều 403. Valid CSRF với body rỗng tới validation 400, không có credential/account login hoặc DB write. |
| Old signed sessions | **PASS 8/8** old-signed session cookies bị từ chối authentication qua HTTP. Chỉ đọc keys/signatures trong memory, không decode identity, không in header hoặc xóa row. |
| Data preservation | **PASS**, đối chiếu read-only bounded **39 bảng** trước/sau HTTP; **30 → 30** session rows, 8 chưa hết hạn. Không save/migrate/seed/revoke hoặc tạo account/file trên serving DB. |
| Real account login / new session / logout | **BLOCKED**: chưa có account serving được phép. Không tìm credentials user/admin hoặc tự tạo account. Fixture PASS bên dưới không thay thế gate này. |

**Signing key: RETIRED — VERIFIED LOCAL RUNTIME. Runtime configuration: VERIFIED** trong scope backend đã kiểm; không suy sang deployment khác. AES reader, các field/bytes ngoài SECRET_KEY và storage/DB credentials giữ nguyên; không khôi phục exposed key hoặc thêm fallback. Old-key verifier vẫn có thể xác minh stored signatures; điều đó không có nghĩa backend mới chấp nhận chúng.

#### Regression mới trên PostgreSQL test riêng

Tái sử dụng `infra/seaweedfs/regression.py`, mỗi suite một DB UUID, chạy **tuần tự**; marker/role/name/port được kiểm trước setup/teardown. Local wrapper `.python/p1_acceptance_checks.py` chỉ cấp password test riêng từ file ignored, giữ raw stdout/stderr trong memory, chỉ xuất/lưu tổng hợp và test names nếu lỗi; không lưu secret/traceback. Không sửa assertion, flags serving hoặc coverage để lấy PASS.

| Gate chạy mới | Kết quả |
| --- | --- |
| Django system check | **PASS** 0 issues, isolated settings. |
| Migration consistency | **PASS** `makemigrations --check --dry-run --settings securedrive.test_settings`, No changes detected; test DB sẵn sàng, **không có migration-history connection warning**. Không apply serving migration. |
| Full Django | **PASS 595 executed / 19 SKIP**, 614 total, **0 failures / 0 errors**, 1086.459s. 19 provider SKIP không tính PASS và không đổi coverage. |
| Enabled-fixture suite | **PASS 72/72**, 0 skip/fail/error, 90.242s; năm labels storage routing/runtime qualification/telemetry/layouts/presigned download như CI. FakeS3/scoped fixture, không kết nối SeaweedFS runtime. |
| Authentication fixture smoke | **PASS 6/6**, 0 skip/fail/error, 9.656s: năm account regressions hiện có và một isolated end-to-end fixture flow mới trong helper ignored. CSRF missing denial, bootstrap, login thật qua APIClient, new session/me, old-key fixture session denial, CSRF logout denial/success, invalidation và password-reset/admin-invitation token checks. Fixture dùng password/retired key ngẫu nhiên riêng và test settings; **không đọc serving credential/key**, không dùng user thật hoặc force-login cho flow mới. |
| Runner không cần DB-using tests | **PASS 2/2**, 0 skip/fail/error, 0.055s; guard lifecycle/marker vẫn chạy. |
| Environment/target/live/repository guards | **PASS 30/30**, 0 skip/fail/error, 25.008s. |
| Repository security | Working-tree và index scan **PASS độc lập** sau khi chốt artifacts: 662 text/5 binary không scan và 419 text/1 binary không scan, 0 findings/blocked. History raw scan vẫn 4 known findings, không gọi history sạch. |
| Dependency / frontend | `pip check` **PASS**. Không thay package/venv/frontend/build; frontend **NOT RUN** trong lượt recovery, kết quả §12.4 là lịch sử. Remote frontend vẫn là gate bắt buộc khi publish được duyệt. |

Commands chạy qua helper `check`, `migrations`, `full`, `enabled`, `auth-fixture`, `no-db`, `guards`; mặc định và enabled/no-db gọi runner hiện có, không live-storage. Auth helper thêm module ignored vào import path của runner, không thay app discovery hoặc bộ 614 tests. Không chạy hai Django suites đồng thời trên cùng test DB. Evidence tổng hợp `.python/p1-final-*.json`, helper code và process attestation đều ignored, không thuộc Git candidate hoặc CI/runtime secret inputs.

**Backup recovery hardening:** phát hiện executor sandbox và operator thực tế khác SID. Backup ban đầu có ba trusted rules cho executor/SYSTEM/Administrators; bổ sung **đúng operator** bằng DACL grant riêng, không broad group. Hiện directory protected/no inheritance từ parent, backup có **4 trusted Allow rules**: operator, executor, SYSTEM, Administrators, 0 unexpected rules. Operator thực tế đã mở kiểm tra được file (không đọc/in nội dung). Không đổi key/config để sửa quyền backup.

#### Git/security disposition và acceptance

- Demo password: **VERIFIED NOT CURRENTLY USED — checked local scope**, 0 matches trong 5 auth rows ở audit đầu lượt; không dùng để login. Hai seed history blobs là cùng material; giữ seed source fix staged. Backup-source fixture finding vẫn INFORMATIONAL.
- Signing key: **RETIRED / local runtime VERIFIED**. Exposed key còn trong history và private backup được bảo vệ, không trong fallback/backend hiện hành. Không rewrite history, rotate thêm hoặc thay AES/storage/DB keys.
- **Operator quyết định giữ publish BLOCKED để review history thêm**, không phải chưa trả lời. Không tự đề nghị/mở gate chỉ vì runtime key đã PASS.
- Candidate: **674 paths**, 654 INCLUDE/20 EXCLUDE; giữ các dependency baseline, seed fix và 9 deletion có sẵn. Report + hai derived manifest/patch cập nhật; source nghiệp vụ/frontend/workflow/dependency giữ nguyên. HEAD/index và current branch giữ nguyên, chưa stage thêm.
- **Commit SHA/acceptance branch/PR/Actions URL mới: chưa có. Remote CI: NOT RUN.** Không commit/push/Draft PR/merge/deploy khi gate đóng. Ba remote jobs phải PASS trên cùng commit SHA sau khi operator cho publish; local PASS không thay remote CI.
- **PENDING ACCEPTANCE / P2 NOT READY**: còn serving login/logout bằng account được phép, history disposition mở gate, candidate integration review và remote CI. Global legacy storage 9000 chưa sẵn sàng là giới hạn file-flow đã ghi nhận, không tự xử lý bằng thay routing hoặc khởi chạy MinIO.

Kết thúc kiểm thử: đã kiểm lại marker/role/database/port, **0 test DB UUID và 0 test-DB connections** còn lại, rồi dừng riêng PostgreSQL test theo runbook, **exited 0**. Đây là dừng test service chủ động sau PASS, không phải dependency failure chưa khắc phục; không down/xóa volume hoặc dữ liệu phục vụ. Kiểm lại **8 Platform containers healthy**, native application PostgreSQL Running và backend PID **23616** vẫn bind đúng loopback 8000/key attestation PASS. Docker/Platform/backend đã duyệt được giữ chạy; Enterprise/MinIO không khởi động. Nếu cần dừng/khôi phục, chỉ dừng PID backend do task tạo khi lỗi hoặc được yêu cầu; không restore exposed signing key. Rollback source chỉ áp dụng delta report/artifacts sau review, không reverse cumulative patch vào working tree có sẵn.

### 12.8 Autonomous acceptance decision & Git/CI integration

Ngày **16/11/2026**, Asia/Bangkok. Người dùng cấp quyền Lead Engineer tự đánh giá security disposition/history, chấp nhận giới hạn kiểm thử phù hợp development, tạo branch/commit/push/Draft PR và nghiệm thu P1 khi remote CI đạt. Quyền mới thay quyết định phải chờ operator history review trước đó; không cấp quyền rewrite published history, force-push/shared branch, thay AES/production credentials, ghi/migrate serving data, merge hoặc deploy.

**Security disposition: KEEP HISTORY / PUBLISH GATE OPEN cho curated development candidate.** Hai seed blobs cùng credential material đã có evidence 0/5 local account matches; source fix bỏ default/in password vẫn được giữ. Django key lịch sử đã **RETIRED — VERIFIED LOCAL RUNTIME**: effective key mới/fallback rỗng trong serving process, chữ ký mới hợp lệ, 8/8 old-session HTTP requests bị từ chối và session rows giữ nguyên. Backup-source finding là fixture informational, không thuộc candidate. Không có evidence mới về credential còn hiệu lực ngoài scope hoặc severe blocker cần xử lý thêm. Giữ history là phương án tối thiểu sau retirement; rewrite không thay thế credential retirement và không được thực hiện. Raw history scan vẫn 4 known findings, không gọi history sạch. Material vẫn có thể được tra cứu và không được tái sử dụng; evidence chỉ chứng nhận local đã kiểm, không bảo đảm deployment khác.

**Authentication acceptance:** positive serving login/logout **NOT VERIFIED — accepted development limitation**, không gắn PASS. Không có test account serving được phép, không tìm credential user/admin hoặc tạo account thật. Chấp nhận giới hạn vì đã có 6 auth fixture tests (real APIClient login/session/CSRF/logout/token), 30 guards và actual serving CSRF/old-session/signing verification. Không cần tạo thêm fixture hoặc chạy lại full regression khi source ứng dụng không đổi.

**Git candidate:** giữ manifest 674 paths, 654 INCLUDE/20 EXCLUDE; kế hoạch 386 commit paths gồm 384 delta và hai derived artifacts, nhóm backend/infra 84, frontend 139, verification 81, docs/artifacts 82. Giữ seed security fix, migrations/routes/fonts/infra/CI và 9 deletions có sẵn. Chỉ stage từng whitelist bằng literal pathspec; không add toàn repo, reset/stash hoặc ghi đè EXCLUDE. Branch acceptance dự kiến `refactor/p1-baseline-acceptance`, base HEAD `d968ebffa0d17f4fce81c2b2f56af5021e60e070`.

Khi đối chiếu index mới, Git rename detection gộp một deletion/addition; dùng `--no-renames` để kiểm đủ paths, không thay source vì cách Git biểu diễn rename. `git diff --cached --check` phát hiện đúng hai dòng trống còn whitespace ở `AccountSettingsContent.tsx`: chỉ bỏ whitespace trên hai dòng này, JavaScript do TypeScript emit giữ nguyên và ESLint đúng file PASS. Giấy phép Poppins OFL giữ nguyên checksum upstream; dòng 21 trailing whitespace của bản gốc được ghi nhận riêng, không sửa license hoặc tắt kiểm tra CI để né lỗi. Không chạy lại full regression cho hygiene không đổi JavaScript.

Nhóm verification có thêm blank line dư tại EOF của `backend/securedrive/test_settings.py` và `frontend/e2e/storage-topology-fixture.ts`; chỉ chuẩn hóa về một newline cuối file. Python AST và JavaScript fixture emit giữ nguyên. Đây là hygiene được index check chứng minh, không đổi isolation, assertion, workflow hoặc hành vi runtime.

Nhóm tài liệu có một trailing space đơn ở roadmap Windows, đã bỏ đúng ký tự đó. Hai patch evidence giữ nguyên context/removed-line whitespace để không làm hỏng patch; kiểm tính đúng bằng apply-check trên các review copies, không trim nội dung patch như source. Source/index security vẫn kiểm toàn bộ artifacts, không miễn trừ credential scanner.

**Current acceptance: FINAL ACCEPTED — development baseline**, ngày **17/11/2026**, trên implementation SHA `40d05a5593b84e20858f04562e878178208af621`. Giữ local evidence §12.7 và bổ sung remote proof bên dưới. Đây là nghiệm thu baseline development/local, không phải production, real-provider write/browser/restore acceptance hoặc serving positive-login PASS. Commit ghi nhận evidence sau đó chỉ cập nhật tài liệu/artifacts; implementation SHA được nghiệm thu và run URLs được giữ cố định để tra cứu, current branch checks theo Draft PR.

**Remote CI lần đầu đã chạy:** bốn commits theo nhóm đã push lên `refactor/p1-baseline-acceptance`, tip `d86987086fe3000e9cdc54cd59a34417480b14d1`, [Draft PR #1](https://github.com/binos2303/BlueDrive/pull/1). [Run 43899445763](https://github.com/binos2303/BlueDrive/actions/runs/43899445763) FAIL có log thực tế: safety/backend dừng ở setup-python vì Ubuntu 26.04 không có binary 3.12.10; frontend lint/typegen/TypeScript đã qua, unit discovery dừng với `rg: command not found`, chưa thực thi tests/build. Đây không phải application assertion failure và skipped downstream steps không tính PASS.

Fix CI tối thiểu: pin hai Python jobs vào `ubuntu-24.04`, giữ Python 3.12.10/dependencies và mọi security/test gate; frontend dùng `find` + NUL-delimited Bash array thay dependency `rg` không có trên runner. Giữ zero-discovery failure và cùng 39 test files; không thêm apt/npm dependency hoặc tắt test. Đối chiếu [manifest binary Python chính thức](https://raw.githubusercontent.com/actions/python-versions/main/versions-manifest.json) xác nhận build linux-x64 24.04 có sẵn. Commit fix `40d05a5593b84e20858f04562e878178208af621` đã vượt cả push/PR workflows; không lấy run FAIL của SHA cũ làm bằng chứng PASS.

| Remote gate trên SHA `40d05a5593b84e20858f04562e878178208af621` | Evidence |
| --- | --- |
| Repository safety | [PASS job 133562392770](https://github.com/binos2303/BlueDrive/actions/runs/43942204201/job/133562392770), source/index scan và guard tests giữ nguyên |
| Backend | [PASS job 133562392349](https://github.com/binos2303/BlueDrive/actions/runs/43942204201/job/133562392349), checkout log khớp exact SHA; system/migrations/pip check PASS, guards 30/30 (1.633s), full 614 total = **595 executed / 19 SKIP**, 0 failures/errors (236.918s); no-DB 2/2 (0.003s), enabled 72/72 (18.584s) |
| Frontend | [PASS job 133562393122](https://github.com/binos2303/BlueDrive/actions/runs/43942204201/job/133562393122), clean npm install/lint/typegen/TypeScript, **159 PASS / 0 fail / 0 skip**, production build **40/40** pages |
| PR workflow | [PASS run 43942215088](https://github.com/binos2303/BlueDrive/actions/runs/43942215088), ba jobs cùng head SHA; PR #1 vẫn Draft |

Manifest 674 rows/20 EXCLUDE và toàn bộ source dependencies được giữ; local editor/evidence/private config không publish. Không reset/stash/force-push/history rewrite hoặc sửa dữ liệu/credential phục vụ. GitHub connector tạo PR bị thiếu permission 403; dùng credential helper Git sẵn có cho GitHub REST fallback, token chỉ trong memory, không log/persist. Không merge/deploy. P2 triển khai trong checkout tách biệt để không tự reload runtime P1 hoặc apply schema mới lên serving database.
