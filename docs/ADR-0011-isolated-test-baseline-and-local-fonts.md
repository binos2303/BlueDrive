# ADR-0011 — Baseline test độc lập và tài nguyên build tại dự án

Ngày: **16/11/2026**, Asia/Bangkok. Phạm vi: P1, development/test/CI; không đổi nghiệp vụ, auth, crypto hoặc storage routing runtime. Kết quả kiểm thử tại [P1 report](REFACTOR_P1_BASELINE_2026-11-16.md); giữ [P0](REFACTOR_P0_BASELINE_2026-11-16.md) làm bằng chứng lịch sử.

## Vấn đề và hiện trạng

`.venv/pyvenv.cfg` trỏ tới CPython 3.12.10 đã mất; Python embeddable dự phòng thiếu `venv`. Runner tạo DB test tên riêng nhưng load settings đọc `.env`, làm các test scenario legacy/mock bị ảnh hưởng bởi routing/runtime-probe flags của hệ thống đang phục vụ. Poppins đã được self-host khi ứng dụng chạy bằng `next/font/google`, nhưng bước build vẫn cần gọi Google để lấy font. CI trước P1 chưa chạy Django/PostgreSQL.

Giống phòng kiểm định dùng chung công tắc với nhà kho: dù mẫu thử nằm riêng, thay cấu hình vận hành vẫn làm kết quả kiểm định thay đổi.

## Quyết định

1. **Một `.venv`, CPython đầy đủ tại dự án.** `infra/bootstrap-python.ps1` dùng package CPython NuGet 3.12.10 được ghim SHA-256, giải nén vào `.python/` ignored và sửa launcher/config của `.venv` tại chỗ. Giữ site-packages; không đổi PATH, registry hoặc Python của ứng dụng khác. `-InstallDependencies` áp dụng requirements đã ghim và `pip check`. Không dùng embeddable Python làm môi trường development lâu dài.
2. **Test settings riêng, tái sử dụng application settings.** `securedrive.test_settings` ngăn dotenv mở file private, import settings gốc trong environment tạm xác định rõ. Middleware, password validators, permission/quota services và DB constraints giữ nguyên. Secret/key/storage credential test sinh ngẫu nhiên cho process; reader AES legacy nhận cùng key test qua process env vì API hiện tại đọc trực tiếp ở đó. Media dùng temporary directory; email dùng locmem, storage endpoint mặc định là `.invalid`.
3. **DB contract riêng.** Chỉ đọc `BLUEDRIVE_TEST_DB_{HOST,PORT,NAME,USER,PASSWORD}`, không đọc `DB_*` runtime. Control DB bắt buộc namespace `bluedrive_test_`; runner vẫn tạo DB test UUID chưa tồn tại và từ chối zero discovery/keepdb. Local dùng `infra/postgres-test.compose.yml`: PostgreSQL 18.6 riêng, loopback 55432, tmpfs, không mount volume ứng dụng/Filer. CI có service PostgreSQL 18.6 riêng và cùng contract.
4. **Ma trận flag theo scenario.** Default của test là source-default OFF, không phải tắt flag runtime. Existing enabled tests dùng `override_settings` và valid scoped binding/FakeS3 fixtures; CI chạy riêng nhóm này ngoài full regression. Không nới ACL, quota, checksum, version hoặc assertion để lấy PASS.
5. **Live storage opt-in riêng.** Runner mặc định ép test settings, không tin `DJANGO_SETTINGS_MODULE` hoặc integration flag kế thừa. `--live-storage` mới dùng runtime settings đã được operator duyệt và đòi `SEAWEEDFS_INTEGRATION=1`; CI chặn mode này. Không chạy mode live trong P1. Provider tests skip không được tính PASS.
6. **Poppins local, cùng nhận diện.** Giữ font Poppins normal 400/500/600/700, `--font-poppins`, `display: swap`; chuyển sang `next/font/local` với bốn TTF nguyên gốc và OFL từ commit cố định của Google Fonts. Không thêm thư viện font hoặc sửa tokens/UI. Asset provenance/checksum tại [font README](../frontend/app/fonts/poppins/README.md).
7. **Repository security và CI.** Index chỉ nhận đúng bản sửa `seed_demo.py` đã có trước P1: bỏ literal/default password và việc in password. Không rewrite history hoặc đổi tài khoản runtime. Safety guard nhận biết đúng biểu thức CI `${{ github.run_id }}-${{ github.run_attempt }}`; các literal hoặc biểu thức arbitrary vẫn bị chặn bằng negative tests. Đây là password public theo lượt chạy cho PostgreSQL test service loopback trên runner tạm, không dùng làm runtime credential. CI giữ action pins, `contents: read`, không giữ checkout credential và không dùng `pull_request_target`.

## Phương án so sánh

| Phương án | Đánh đổi / kết luận |
| --- | --- |
| Cài lại Python toàn máy | Có full runtime nhưng ảnh hưởng workstation; chọn base runtime trong dự án. |
| Tạo venv thứ hai | Tăng lệch dependency/IDE; sửa đúng `.venv` hiện có. |
| Chỉ export routing OFF trong shell | Chưa cách ly dotenv, DB, key, email, media hoặc các flags khác; chọn test settings có contract và guard tests. |
| Copy toàn bộ settings sang file test | Dễ lệch middleware/security về sau; import cấu hình gốc với nguồn env được kiểm soát. |
| Dùng SQLite hoặc bỏ constraints/hash checks | Không kiểm được PostgreSQL/isolation thực; loại bỏ. |
| Thêm binding tùy tiện cho mọi legacy test | Đổi ý nghĩa scenario compatibility; giữ legacy OFF, enabled case có fixture riêng. |
| Đổi font hoặc mock download font | Lệch nhận diện hoặc không kiểm build thật; dùng Poppins nguyên gốc tại dự án. |

## Hệ quả, rollout và khôi phục

- Test commands cần test PostgreSQL/role/password riêng; không còn tự mượn credential trong `.env`. Live runbook phải dùng opt-in mới. CI default không cần storage/account/runtime secrets.
- Requirements ghim thêm năm dependency bắc cầu **đúng bản đã cài**, không nâng package: jmespath, python-dateutil, s3transfer, six, urllib3. Không đưa `git-filter-repo` đã có local vào dependency ứng dụng.
- TTF đầy đủ có tổng dung lượng 632.200 bytes; giữ glyph ngoài Latin nhưng payload khác font subset Google trước đây. Không gọi đây là cải thiện performance; cần tính font vào phép đo sau.
- Không có migration hoặc runtime rollout. `.env`, data/key, serving process, routing và source volumes được giữ nguyên. PostgreSQL test chỉ chứa fixture; dừng đúng test project sẽ mất tmpfs, không có volume thật để xóa.
- Khôi phục source theo patch riêng P1 sau review, không reverse toàn bộ diff với HEAD. Giữ bản Python base và `.venv` đang chạy được; config cũ ở `.python/pyvenv.before-repair.cfg` chỉ để đối chiếu, phục hồi nó sẽ đưa lại đường dẫn Python đã hỏng. Không tự bỏ sửa bảo mật đã đưa vào index.
- Git history vẫn chứa default credential cũ. Source/index PASS không chứng nhận account runtime đã được đổi password; rotation hoặc rewrite history là phạm vi riêng cần duyệt.
- Workflow đã viết và các bước tương đương được kiểm tra local; GitHub remote run cần commit/push do người dùng thực hiện. Không coi kiểm tra YAML là một Actions run thành công.

## Bổ sung P1.1 — hardening ngày 16/11/2026

Điểm 2–3 và 5 ở trên mô tả quyết định P1 ban đầu; P1.1 siết contract sau khi kiểm tra các service đọc environment trễ. `patch.dict` trả environment cũ khi hết scope, nên chỉ cách ly lúc import không ngăn storage connection profiles/Prometheus lấy alias credential runtime sau đó. Chọn allowlist suốt process test thay vì blacklist tên credential không thể biết hết; vẫn cho fixture cấp env theo scope. Giữ dotenv disabled, vô hiệu AWS credential file/metadata fallback và libpq passfile; không giữ HOME/APPDATA hoặc biến runtime arbitrary. Chỉ reader AES nhận key test đã sinh. Process shell/serving bên ngoài không bị đổi.

Không chấp nhận endpoint PostgreSQL tùy ý dù tên DB có prefix test. `securedrive/test_environment.py` định nghĩa hai profile cố định: local `127.0.0.1:55432`, CI `127.0.0.1:5432`, cùng control DB `bluedrive_test_control` và role `bluedrive_test`. Override khác profile bị từ chối trước connect; hostaddr cố định tránh libpq environment đổi địa chỉ. Runner kiểm lại config, UUID và identity/marker của control server trước setup và teardown. Marker public chỉ là guard chống chọn nhầm, không phải cơ chế xác thực chống operator có quyền sửa server. Password test riêng vẫn bắt buộc để kết nối.

Marker do init SQL read-only của Compose test tmpfs hoặc CI service bootstrap đặt; runner không tự ghi marker vào server lạ. Nếu guard teardown phát hiện đích lệch, nó dừng và để lại DB fixture để operator kiểm tra thay vì xóa theo cấu hình chưa tin cậy. `manage.py test --settings securedrive.test_settings` bị chặn trước lifecycle, hướng dẫn dùng runner đã guard; check/makemigrations vẫn dùng settings này bình thường.

Live provider phải có `--live-storage --confirm-live-storage <approved-fixture-scope> <labels>` và gate integration; CI luôn chặn. Scope CLI ghi nhận xác nhận của operator, không thay quyền vận hành trong runbook. Live chỉ dùng nguồn cấu hình storage runtime; DB vẫn phải là target test được duyệt. Không chạy live trong P1.1.

Giống phòng kiểm định giữ chìa khóa riêng suốt ca và kiểm biển nhận diện trước khi mở/đóng kho mẫu. Chỉ nhìn tên mẫu hoặc thay chìa khóa lúc mở cửa không đủ ngăn lấy nhầm hàng thật.

Rollback theo delta P1.1 riêng sau review; không reverse thay đổi khác với HEAD. Bỏ hardening sẽ mở lại rủi ro đã xác minh. Không cần migration hay thay credentials/runtime. Nghiệm thu đầy đủ P1 vẫn đợi remote Actions PASS trên commit thực chứa các file đã review.

Nguồn kiểm chứng: [Python patch.dict lifecycle](https://docs.python.org/3.12/library/unittest.mock.html#patch-dict), [PostgreSQL libpq environment](https://www.postgresql.org/docs/18/libpq-envars.html), source Django 5.2.17 đã cài (`DiscoverRunner.setup_databases/teardown_databases`).

## P1.1 Final Acceptance — giới hạn live gate

Bổ sung này thay cách nạp live settings ở các quyết định P1/P1.1 ban đầu: cả default và live đều dùng `securedrive.test_settings`. Giữ DB profile/UUID/marker/credential guards, media tạm, email locmem, keys test và endpoint/registry test; không import settings runtime ngoài nguồn env đã cách ly. Chỉ cấp lại SeaweedFS fixture env được allowlist. Không đọc serving dotenv hoặc chạy gate provider thật trong công việc final acceptance.

Live chỉ nhận hai classes đã review: `files.tests.test_seaweedfs_integration.SeaweedFSIntegrationTests` và `files.tests.test_seaweedfs_finalizer_integration.SeaweedFSFinalizerIntegrationTests`. Hai module tương ứng là aliases được chuẩn hóa thành classes, không discovery cả module; nhãn app/path/method/wildcard/MinIO/nhãn trộn không được duyệt bị từ chối trước `django.setup()` và trước tạo media/DB/client/email. Chọn class thay nhãn app giữ nguyên tests nghiệp vụ/default coverage và ngăn chạy thêm test có quyền ghi vào runtime do chọn nhầm label.

Bucket bắt buộc `bluedrive-test-<scope>` khớp xác nhận scope và đã có ownership/credential policy được operator duyệt riêng. Chỉ HTTP loopback có port tường minh: internal IP `127.0.0.1`, public IP đó hoặc `s3.localhost` được gate HTTP ghim TCP loopback giữ nguyên host ký. Chặn userinfo/path/query/fragment/whitespace và credential thiếu; không lấy AWS/runtime fallback. Provider permission/integrity/denial assertions giữ nguyên. Prefix/loopback chống nhầm target, không thay quyền storage; harness không bootstrap bucket, đổi policy/CORS/versioning hoặc rotate credential.

Giống chỉ cấp quyền vào một phòng mẫu có biển tên và chìa khóa riêng: danh sách người được vào phòng chưa đủ nếu họ vẫn dùng tủ hồ sơ/email/kho hàng của bộ phận đang phục vụ. Ràng buộc này tách cả labels lẫn tài nguyên có thể ghi.

Disposition history, Git paths theo nhóm và evidence của lượt acceptance ghi nối tiếp trong P1 report; không tạo tài liệu quyết định trùng lặp. Remote Actions trên đúng candidate commit và operator disposition cho credential từng có khả năng dùng thật vẫn là gate trước P2.

## Nguồn

- [CPython 3.12 Windows NuGet](https://docs.python.org/3.12/using/windows.html#the-nuget-org-packages), [package 3.12.10](https://www.nuget.org/packages/python/3.12.10), [venv](https://docs.python.org/3.12/library/venv.html). Package SHA-256 trong bootstrap; executable quan sát có Authenticode hợp lệ của Python Software Foundation.
- [Django 5.2 advanced testing](https://docs.djangoproject.com/en/5.2/topics/testing/advanced/) và source đã cài của Django/python-dotenv: test DB lifecycle, override_settings, `PYTHON_DOTENV_DISABLED`.
- Tài liệu Next.js 16.3.3 đã cài: `frontend/node_modules/next/dist/docs/01-app/01-getting-started/13-fonts.md`, `01-app/03-api-reference/02-components/font.md`.
- [GitHub PostgreSQL service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).
