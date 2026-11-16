# ADR-0006 — Ngữ cảnh dự án và hướng dẫn phát triển

- Ngày: 10/11/2026.
- Trạng thái: áp dụng cho quy trình phát triển theo yêu cầu thiết lập project context; không đổi kiến trúc hay triển khai runtime.
- Phạm vi: hướng dẫn Codex, bản đồ source và nơi lưu quyết định dài hạn.

## Vấn đề

Repository đang phát triển có nhiều thay đổi chưa commit, README theo từng tầng, ADR-0001 đến ADR-0005, runbook và báo cáo có ngày. Chỉ có `frontend/AGENTS.md` với khối Next.js tự sinh; chưa có nội quy hoặc bản đồ ở root. Một số tài liệu là đề xuất hoặc baseline cũ, nên đọc một báo cáo riêng có thể hiểu sai route, encryption hoặc tiến độ chuyển storage.

## Quyết định

- `AGENTS.md` root là nguồn nội quy chính: trước mỗi công việc đọc file này, phần liên quan trong `MAP.md` và hướng dẫn phạm vi con trước khi sửa code. Giữ nguyên hướng dẫn Next.js tự sinh ở frontend.
- `MAP.md` root ánh xạ trách nhiệm, điểm vào và tài liệu theo nhu cầu, không chép mọi file hoặc output. Cập nhật cùng thay đổi module quan trọng; không dựa vào khả năng tự nạp `MAP.md` của công cụ.
- Giữ một hệ quyết định lâu dài: nối tiếp `docs/ADR-NNNN-*.md`. Quy tắc bảo mật/nghiệp vụ hiện có được dẫn tới ADR, model/service/test đúng phạm vi, không chép sang một kho context mới.
- README và `docs/DEVELOPMENT.md` giữ vai trò setup/quy trình; runbook giữ lệnh/gate vận hành; handoff và evidence giữ kết quả theo thời điểm. Đề xuất, code và runtime acceptance phải ghi tách bạch về trạng thái.
- Khi tài liệu và source không khớp, đối chiếu route/model/migration/service/test hiện tại để xác minh implementation; runtime cần bằng chứng môi trường có ngày. Việc một tài liệu liệt kê lệnh không tự cho phép thực thi lệnh đó.

Giống một tòa nhà: nội quy ở cửa vào, sơ đồ chỉ đường tới phòng, còn hồ sơ quyết định giải thích vì sao phòng được bố trí như vậy.

## Phương án không chọn

| Phương án | Lý do |
| --- | --- |
| Tạo `docs/context/` song song với `docs/ADR-*` | Hai nơi cùng giữ quyết định sẽ dễ lệch nhau; hệ ADR hiện có đã phù hợp. |
| Chép toàn bộ tài liệu/lịch sử vào `AGENTS.md` hoặc `MAP.md` | Tăng ngữ cảnh đọc, lặp quy tắc và giữ trạng thái dễ lỗi thời. Dùng liên kết có mục đích. |
| Bắt buộc một công cụ graph/index ngoài để tìm code | Thêm dependency vào quy trình cho nhu cầu có thể giải quyết bằng bản đồ ngắn và tìm source. Graphify là công cụ hỗ trợ tùy nhu cầu, không thay source/ADR và không là điều kiện khởi động. |
| Viết lại hướng dẫn frontend tự sinh | Next.js quản lý khối đó; hướng dẫn toàn dự án đặt ở root và được kết hợp với hướng dẫn cục bộ. |

## Hệ quả và cách duy trì

Một số liên kết phải được bảo trì khi thay module; đổi lại không cần đồng bộ nhiều bản nội quy/kiến trúc. ADR mới chỉ tạo khi có quyết định thực sự, ghi vấn đề, lựa chọn, trade-off, hệ quả, trạng thái và nguồn. Quyết định thay thế phải dẫn ADR cũ và chỉ rõ phần bị thay, giữ khả năng truy vết. Không lưu secrets, hội thoại dài hoặc suy đoán như sự thật.

Phiên bản trong MAP là snapshot đối chiếu manifest/lockfile, không là cam kết runtime của mọi máy. Đổi dependency, API hoặc kiến trúc vẫn phải đánh giá/phê duyệt theo `AGENTS.md`; ADR này không cấp quyền refactor, cutover, thay dữ liệu hay bật feature flag.

Nguồn: [AGENTS.md](../AGENTS.md), [MAP.md](../MAP.md), [development workflow](DEVELOPMENT.md), ADR-0001–0005 và [hướng dẫn AGENTS.md chính thức của OpenAI](https://learn.chatgpt.com/docs/agent-configuration/agents-md). Codex kết hợp hướng dẫn từ root tới thư mục làm việc; vì vậy root giữ nội quy ngắn, phần chi tiết được mở theo liên kết.

## Bổ sung engineering harness — 10/11/2026

Giữ chu trình sáu bước và bảng chọn test trong `docs/DEVELOPMENT.md`, liên kết từ AGENTS/MAP thay vì tạo framework/SPEC/PLAN mặc định. Hai project skill chỉ đóng gói review API/quyền và nghiệm thu storage có tương tác nhiều tầng; regression và UI checklist tiếp tục dùng runner/design system hiện có.

Thêm một guard Python chuẩn cho source/index và CI GitHub tối thiểu, vì repo chưa có cơ chế kiểm tra này và remote đã xác minh là GitHub. CI chỉ giữ quyền đọc, ghim action commit và chạy kiểm tra repository/frontend không cần secret. Backend PostgreSQL, build/browser/live storage vẫn là gate riêng theo phạm vi, tránh hiểu CI xanh là nghiệm thu vận hành. Không chọn một hệ plugin/MCP, dependency quét mới hoặc report cho từng thay đổi nhỏ.

Trade-off: guard theo pattern cần test và có giới hạn nhận diện; đổi lại chạy local/CI mà không đọc private env hay cần thêm package. Nó không thay secret scanning đầy đủ, lịch sử Git hoặc quy trình xử lý credential đã lộ. Các giới hạn và cách chạy được giữ tại DEVELOPMENT để tránh nhiều bản hướng dẫn lệch nhau.
