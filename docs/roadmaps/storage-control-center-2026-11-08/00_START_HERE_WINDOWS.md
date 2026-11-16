# 00 — Bắt đầu triển khai trên Windows, không chạm dữ liệu thật

## 1. Giải nén bộ hướng dẫn trong Downloads
Dùng PowerShell:
```powershell
$Root = Join-Path $env:USERPROFILE 'Downloads'
$Package = Join-Path $Root 'BlueDrive_Storage_Control_Center_AZ_2026-11-08.zip'
$Guide = Join-Path $Root 'BLUEDRIVE_SCC_AZ'
Expand-Archive -LiteralPath $Package -DestinationPath $Guide -Force
Get-ChildItem -LiteralPath $Guide | Select-Object Name
```
Gói này **chỉ chứa hướng dẫn và kế hoạch**, không chứa trình tự động cài MinIO hoặc lệnh xóa dữ liệu.

## 2. Kiểm tra repo hiện hữu
```powershell
$Repo = 'C:\Users\dang2\Project\SecureDrive'
if (-not (Test-Path -LiteralPath (Join-Path $Repo 'backend\manage.py'))) { throw 'Sai duong dan repo' }
Set-Location -LiteralPath $Repo
git status --short
git branch --show-current
```
Nếu repo đang có thay đổi chưa commit, **không reset, không clean, không stash tự động**. Ghi lại hiện trạng và triển khai trên một nhánh có chủ đích khi người dùng xác nhận.

## 3. Công việc cần làm đầu tiên: Sprint 0
- Đọc `README.md`, `01_MASTER_PLAN.md`, `02_ARCHITECTURE_SOURCE_MAP.md`.
- Mở `09_CODEX_PROMPTS.md`, sao chép *Prompt 0* cho Codex cùng repo local.
- Codex chạy kiểm kê/test trên test DB riêng, xuất log và báo cáo về Downloads.
- Phê duyệt gate G0 trước khi giao Prompt 1. Không đưa toàn bộ prompt S0–S8 vào một lần chạy tự động.

## 4. Những lệnh kiểm tra baseline an toàn (không tự kích hoạt dịch vụ)
**Backend** (khi `.venv` và DB test đã cấu hình đúng):
```powershell
Set-Location "$Repo\backend"
& "$Repo\.venv\Scripts\python.exe" manage.py check
& "$Repo\.venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```
**Frontend** (nếu dependencies đã được cài):
```powershell
Set-Location "$Repo\frontend"
npx tsc --noEmit
npm run lint
npm run build
```
Các lệnh trên không thay thế integration tests. `npm run build` có thể tạo `.next` trong repo; chỉ chạy khi đã xác nhận điều kiện làm việc. Tránh chạy tests trên database production hoặc MinIO đang có dữ liệu thực.

## 5. Cách bàn giao cho Codex
Dán: "Hãy đọc bộ kế hoạch tại `<Downloads>\\BLUEDRIVE_SCC_AZ`, bắt đầu bằng `09_CODEX_PROMPTS.md` mục Prompt 0. Trước khi sửa mã hãy xác nhận source map và các điểm khác biệt với repo hiện tại. Không thực thi các bước destructive, giữ nguyên thay đổi working tree, xuất báo cáo + logs về Downloads."

## 6. Dấu hiệu hoàn thành S0
- `git diff` được giải thích; không mất thay đổi cũ.
- Danh sách models/API/routes/UX hiện tại và thiếu sót có dẫn chiếu file.
- Test baseline với PASS/FAIL/SKIPPED thực tế.
- MinIO edition/license/version và topology được xác định cho **lab**.
- Rủi ro đã được ghi; chưa bật tự động deploy node.
