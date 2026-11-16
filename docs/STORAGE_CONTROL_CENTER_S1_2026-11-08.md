# Storage Control Center — S1 inventory và RBAC

Ngày: 08/11/2026. Nhánh: `feature/storage-control-center-s1-20261108`.

Cập nhật 09/11/2026: đây là hồ sơ S1 tại thời điểm bàn giao. S2 đã áp dụng schema local sau backup và triển khai connection/pinning; trạng thái mới nằm trong `STORAGE_CONTROL_CENTER_S2_2026-11-09.md`.

## Kết quả

Đã triển khai backend S1 sau yêu cầu “bắt đầu triển khai”: domain inventory, API scoped cho Platform/Organization, quyền storage riêng, luồng Owner tự cấp/thu hồi quyền và audit. **Release check: 497 test, 488 PASS, 9 SKIPPED; không FAIL.** 49 test S1 được bổ sung, gồm năm bài concurrency hai kết nối và một bài schema rollback/forward bảo toàn metadata legacy.

Bốn cờ rollout vẫn mặc định OFF. Không áp dụng migration lên DB ứng dụng đang chạy, không tạo cluster demo, không gọi MinIO thật hoặc triển khai agent. Chưa có React Flow canvas trong S1; phần đó thuộc S3. Chưa thay UploadSession, StorageLocation, factory, quota hoặc luồng upload/download để dùng binding mới.

Source đã sẵn sàng cho review S1. Nghiệm thu kết nối storage thật, migration trên môi trường ứng dụng và các sprint S2–S8 vẫn còn lại. Lab/edition/license và auth state trong ZIP source cũ vẫn giữ trạng thái đã ghi ở S0; lượt này không tự xử lý bằng cách đổi credential hoặc revoke phiên người dùng.

## 1. Quyết định trước khi sửa

Áp dụng `ponytail` và skill `bluedrive-storage-control-center` đi kèm lộ trình. Giữ một app `infrastructure` cho domain có quan hệ chặt chẽ, một API module dùng chung policy cho hai scope; không tạo thêm service/microservice hoặc framework mới. Không dùng skill chỉnh frontend vì S1 không sửa giao diện. Báo cáo được rà theo cách viết ngắn, rõ của `humanizer` đã áp dụng trong công việc này.

Tenant hiện chỉ personal/business và dedicated Platform Admin không có personal tenant. So với việc thêm Tenant.Kind.PLATFORM vào toàn bộ accounts, hoặc đứng tên cluster bằng tài khoản admin, phương án ít ảnh hưởng hơn là owner scope rõ trên StorageCluster:

- Platform cluster: `kind=platform`, tenant bắt buộc NULL; Platform là chủ quản cố định.
- Organization cluster: `kind=enterprise`, tenant bắt buộc là business; owner không đổi sau tạo.

DB check/trigger và API đều bảo vệ quy tắc này. Đây là điều chỉnh có chủ đích so với cột tenant bắt buộc trong bản plan; chi tiết tại `docs/ADR-0002-storage-inventory-ownership.md`. Không thêm Tenant giả hoặc Organization model trùng lặp.

Giống kho công ty và kho khách hàng: kho công ty thuộc công ty chứ không thuộc tài khoản cá nhân của người quản lý; kho khách hàng phải ghi rõ khách hàng sở hữu.

## 2. Source và hành vi đã triển khai

| File / nhóm | Thay đổi | Vì sao |
|---|---|---|
| `backend/infrastructure/models.py` | StorageCluster, ServerPool, StorageNode, NodeDisk | Biểu diễn inventory/pool/disk bằng UUID ổn định; IP không là định danh node; không dùng record để suy health |
| Cùng module | StorageBinding | Chuẩn bị policy mapping; cùng tenant/config/workspace, cluster verified trước active, một cluster active mỗi business tenant trong MVP |
| Cùng module | TopologyLayout | Preference cá nhân/shared có revision riêng, tách khỏi revision topology; S1 chỉ đọc |
| Cùng module | ClusterOperationJob | Idempotency, plan hash, lease counter và một operation active; constraint bắt buộc dry_run=True trong S1 |
| Cùng module | ClusterAuditEvent | Audit của cluster hoặc của tenant cho thay đổi quyền trước khi có cluster; không có API sửa/xóa event |
| Cùng module | StorageAccessGrant | Capability riêng gắn Membership, không dùng quyền nội dung hoặc Org Admin để tự cấp quyền hạ tầng |
| `backend/infrastructure/api.py` | Scoped GET và Owner access administration | Dùng chung implementation nhưng tenant/principal phía server quyết định phạm vi; không gọi provider |
| `backend/infrastructure/urls.py` | Hai namespace dùng chung patterns | Không nhân đôi logic Platform/Organization |
| `backend/infrastructure/apps.py`, `__init__.py` | Đăng ký app domain | Giữ inventory ngoài dashboard/accounts monolith |
| `backend/securedrive/settings.py` | Thêm app infrastructure | Đăng ký schema; không bật rollout flags |
| `backend/securedrive/urls.py` | Hai include API | Platform trong prefix admin hiện hữu, giữ middleware chặn Platform Admin vào product API |
| Hai migration infrastructure | Schema additive, FK/trigger | Chặn dữ liệu sai ngay tại DB, kể cả ORM không gọi full_clean |
| `backend/infrastructure/tests.py` | API/constraint/concurrency/migration tests | Kiểm tra boundary, dữ liệu sai, race, CSRF và rollback thực trên PostgreSQL |
| `backend/accounts/test_storage_inventory_acceptance.py` | Hai acceptance API | Ghi FAIL trước khi endpoint tồn tại, sau đó PASS mà không nới assertion |
| API contract/data model/ADR/progress/report | Tài liệu đúng implementation | Phân biệt endpoint hiện có với đề xuất v1 và các sprint chưa làm |

Nhánh mới giữ nguyên toàn bộ dirty working tree trước đó, không reset/stash/commit. Nhánh chưa có PR hoặc commit riêng; các thay đổi cũ vẫn cần phân loại khi review, không coi toàn bộ diff của nhánh là thay đổi S1.

## 3. API và quyền

Prefix Platform: `/accounts/api/admin/storage/`. Chỉ active Platform Admin xem cluster kind platform. Plain staff không được cấp quyền chỉ vì is_staff. Platform Admin không thể xem Organization bằng cách dùng UUID cluster hoặc ngay cả khi có membership/grant tại đó.

Prefix Organization: `/accounts/api/tenants/{tenant_uuid}/storage/`. User active, tenant business active, membership active và explicit `storage.view` mới đọc được inventory. Tenant trong route chỉ là selector; không cấp quyền. Query `tenant_id` và body không được dùng để đổi phạm vi.

Các GET đã có:

- `capabilities/`, `clusters/`, `clusters/{cluster_id}/`.
- `clusters/{cluster_id}/topology/`.
- `clusters/{cluster_id}/nodes/`, `nodes/{node_id}/` trong cùng cluster.
- `clusters/{cluster_id}/disks/`, `events/`.
- `clusters/{cluster_id}/operations/`, `operations/{job_id}/` trong cùng cluster.

List dùng envelope `{count,page,page_size,has_more,results}`, page_size mặc định50 và tối đa100; sort có ID tie-breaker. Có tìm kiếm tên cluster/hostname bằng q giới hạn100 ký tự. Dùng pagination theo convention admin hiện tại, không tuyên bố đã triển khai contract cursor của namespace v1 đề xuất.

Topology snapshot giới hạn500 nodes,500 pools,2000 disks. Vượt giới hạn trả422 `topology_snapshot_too_large` để chuyển sang list có phân trang. Không trả thành công với dữ liệu bị cắt lặng lẽ. Query count không tăng theo từng node/disk trong bài1→41 node. Chưa đo p95, FPS hoặc latency với500 node trên staging.

Health luôn Unknown/source not_collected/stale trong S1, kể cả khi connection được ghi verified hoặc node có agent UUID. Last_seen và capacity vẫn là inventory, không chứng minh thiết bị hoạt động. Chưa có collector hoặc agent enrollment; UUID inventory không phải chứng nhận mật mã.

API không trả credential_ref, raw config, idempotency key, raw provider error hoặc JSON opaque. Labels/audit/layout dùng phép chiếu allowlist; tọa độ phải finite, thuộc node đúng cluster. JSON sai kiểu hoặc số quá lớn không làm snapshot500. Không có request network tới IP/hostname inventory.

## 4. Owner cấp quyền tự phục vụ

Chỉ GET inventory sẽ khiến Owner chưa có storage grant phải sửa DB để dùng tính năng. Đã bổ sung ngoại lệ quản trị metadata rõ ràng, không phải thao tác provider:

```text
GET   <organization-prefix>access/{membership_id}/
PATCH <organization-prefix>access/{membership_id}/
GET   <organization-prefix>access/events/
```

Chỉ Organization Owner đang active được dùng, không cần storage grant trước đó. Org Admin, storage.configure hoặc Platform Admin không có quyền delegate. Owner có thể cấp storage.view cho chính mình một cách chủ động.

PATCH yêu cầu session CSRF và đúng ba trường:

```json
{
  "permissions": ["storage.view"],
  "expected_permissions": [],
  "reason": "Owner enables inventory access"
}
```

Supported capabilities: storage.view/configure/operate/approve/monitor. Cấp quyền không tạo quyền đọc file, không mở execute operation. Capabilities luôn báo operations_enabled=false và routing_enabled=false trong S1.

Tenant/member/user được khóa khi ghi. Hai form cùng dựa vào một tập quyền cũ sẽ có một update hiệu lực, form còn lại409 `storage_access_conflict`; không ghi đè lặng lẽ. Retry với cùng desired set là no-op và không tạo audit trùng. Thu hồi vẫn hoạt động khi thành viên đã bị suspend hoặc user inactive; cấp quyền mới cho đối tượng inactive bị từ chối.

Thay đổi grant và audit before/after/reason diễn ra trong cùng transaction. Audit scope tenant có từ trước khi có cluster, Owner không cần Platform hỗ trợ bootstrap. Endpoint inventory còn lại chỉ đọc; POST/PATCH/DELETE không được hỗ trợ. Chưa có UI cấp quyền ở sprint này.

## 5. Schema, migration và compatibility

`0001_initial` tạo chín model mới và constraints. `0002_inventory_integrity` thêm composite FKs và PostgreSQL triggers:

- Node/pool phải cùng cluster; binding workspace/config phải cùng tenant.
- Enterprise cluster phải thuộc business tenant, owner immutable.
- Storage grant phải được Owner cùng Organization delegate.
- Active binding cần ready cluster có verified_at và active config đúng provider.
- Khóa tenant khi kích hoạt binding để hai giao dịch không thể active hai cluster business khác nhau ở hai workspace.
- Tenant kind không đổi khi đã có inventory/binding/grant/audit liên quan.

Giữ unique tenant/provider của StorageConfig. Không chỉnh cột, không backfill hoặc xóa StorageConfig, StorageLocation/provider_version_id hoặc UploadSession. Chưa dùng StorageBinding mới để định tuyến data plane. Schema migration initial chỉ được hoàn thiện trong DB thử trước lần phát hành đầu, không sửa migration đã apply trên DB ứng dụng.

Operation unique active bao gồm needs_attention: khi kết quả cần đối soát, không được tạo operation active khác chồng lên nó. Có thể lưu draft plan khác; chưa có execute dispatcher hoặc worker SCC. Constraint dry_run=True vẫn chặn job thật ngay tại DB.

Bài migration lên/xuống dùng MigrationExecutor trên DB thử, tạo StorageConfig/FileVersion/StorageLocation legacy sentinel, drop/recreate app schema rồi xác nhận object_ref/provider_version_id cũ vẫn nguyên. Không gửi request storage. Đây không phải restore drill PostgreSQL+MinIO+keys.

**Migration chưa apply lên DB ứng dụng.** Lệnh rollout sau khi duyệt và sao lưu phù hợp là `python backend/manage.py migrate infrastructure`; chưa chạy lệnh này trên môi trường đang dùng. Bật feature flag là bước riêng; không tự bật chỉ vì schema đã có.

## 6. Kiểm thử và bằng chứng

| Lượt | Kết quả | Ý nghĩa |
|---|---|---|
| Acceptance inventory trước code | 2 FAIL404 | Hai endpoint chưa tồn tại; test assertion giữ nguyên |
| Acceptance Owner delegation trước code | 3 FAIL404 | Bootstrap/grant/audit/conflict chưa có; test assertion giữ nguyên |
| Lượt focused đầu | 39 test,4 ERROR fixture | TransactionTestCase flush làm mất plan seed; sửa fixture bằng serialized_rollback để phục hồi baseline migration data |
| Focused S1 | 48 PASS, sau bổ sung hardening49 PASS | Role, API, FK/constraints, CSRF, audit, layout projection, paging,5 races, migration |
| Full trước hai hardening cuối | 496 tests:487 PASS,9 SKIP | Không regression legacy ở thời điểm đó |
| **Full release cuối** | **497 tests:488 PASS,9 SKIP** | Code/schema cuối, 59,722s; không FAIL |
| Django check cuối | PASS | Không system-check issue |
| Migration dry-run cuối | PASS | No changes detected |
| Whitespace diff | PASS | Các file tracked được sửa; không xóa thay đổi có sẵn |

Lượt acceptance đầu chỉ dùng DB test tên ngẫu nhiên trên PostgreSQL local. Các lượt xác minh S1 và release dùng **cluster PostgreSQL18.6 mới riêng, loopback, role/password mới, test DB chưa tồn tại**, media tạm, email locmem, storage HTTP ngoài mock bị chặn. Dùng fast hasher chỉ trong tiến trình test. Các cluster đều được dừng và xóa sau lượt chạy, có isolation JSON.

Năm bài hai connections: trùng agent identity, operation active, idempotency key, hai business bindings khác cluster, và hai form Owner cạnh tranh quyền/audit. Mỗi bài chạy trong focused và full suite; không suy thành bài nhiều worker/MinIO thật.

Chín test skip là integration MinIO opt-in cần môi trường riêng. Không sửa test hoặc bật opt-in trên bucket ứng dụng để làm xanh. Các lỗi A01–A12 đã xác nhận trước đó nằm ở luồng cũ vẫn là phát hiện độc lập; S1 không được ghi là đã sửa chúng chỉ vì suite hiện tại xanh.

Không sửa frontend trong S1 nên không lặp lại TS/lint/build/Chrome của S0. Chưa nghiệm thu canvas, drag/layout-save, telemetry real-time, agent hoặc provisioning. API integration ở đây sử dụng Django test client với session/middleware/CSRF thực của test DB, không phải API đang chạy với tài khoản người dùng thật.

## 7. Rủi ro còn lại, rollback và gate tiếp theo

- Chưa có dữ liệu cluster runtime, secret resolver, endpoint verification/SSRF allowlist, binding resolver hoặc session-pinned routing. Đây là S2, cần môi trường/credential_ref phù hợp.
- Chưa có API connect/verify hoặc tạo Organization/cấp Owner. S1 chỉ thêm domain và phân quyền storage; directory Organization hiện hữu vẫn giữ vai trò cũ.
- Chưa có canvas/SSE/collector/agent/tasks mTLS/provisioning/maintenance. Không gắn nhãn Live/Healthy hoặc hứa HA.
- Migrations dùng PostgreSQL và thêm trigger lên update Tenant.kind; cần review cùng các chính sách chuyển loại tenant nếu sau này có tính năng đó.
- Quyền access administration có audit qua API; DB owner vẫn là vùng tin cậy có quyền sửa dữ liệu trực tiếp. Không tuyên bố audit bất biến chống database superuser.
- S1 chưa có support grant chéo tenant hoặc rate-limit chuyên biệt/step-up cho provisioning. Không có provisioning endpoint để kích hoạt ở sprint này.

Rollback rollout: giữ/tắt feature flag, giữ schema additive nếu đã có inventory/audit. Không reset cả file hoặc cả branch vì working tree có thay đổi cũ. Không chạy migrate zero với dữ liệu cần giữ; bài rollback schema chỉ được chạy trong DB thử. Không có dữ liệu object hoặc routing mới cần chuyển ngược trong S1.

S1 đã đủ bằng chứng review source/schema. Gate tiếp theo là duyệt S1 để bắt đầu S2 Connect Existing read-only và resolver theo lộ trình; việc verify MinIO thật tiếp tục phụ thuộc lab riêng. Yêu cầu bắt đầu triển khai của người dùng không được diễn giải thành phê duyệt license, format disk, deploy node hay đổi cấu hình storage đang dùng.

Skill workflow đi kèm có thể tiếp tục dùng cho S2; chưa cần tạo một skill trùng chức năng. ADR ownership, schema tests, scope tests và evidence packaging là phần có thể tái sử dụng cho các sprint sau.

## 8. Hồ sơ bàn giao

Workspace: `frontend/test-results/storage-control-center-s1/`. Downloads: `BLUEDRIVE_SCC_S1/` gồm báo cáo, ADR, progress, log release/focused/red tests, isolation JSON và manifest hash. Không copy `.env`, auth state, CLI config hoặc source ZIP cũ.

API/data model chi tiết được cập nhật trong `docs/API_CONTRACT_V1.md`, `docs/DATA_MODEL_MVP.md`; ownership ở ADR-0002. Bộ hướng dẫn gốc trong `docs/roadmaps/storage-control-center-2026-11-08/` được giữ nguyên để đối chiếu MANIFEST.
