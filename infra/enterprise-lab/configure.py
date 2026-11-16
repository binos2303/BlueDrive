"""Tạo cấu hình enterprise lab bằng generator chung; không thay Platform secrets."""
import importlib.util
import os
from pathlib import Path

from dotenv import dotenv_values

BASE = Path(__file__).resolve().parents[1] / "seaweedfs"
_shared_spec = importlib.util.spec_from_file_location("bluedrive_seaweed_configure", BASE / "configure.py")
if _shared_spec is None or _shared_spec.loader is None:
    raise RuntimeError("Thiếu bộ sinh cấu hình chung SeaweedFS.")
_shared = importlib.util.module_from_spec(_shared_spec)
_shared_spec.loader.exec_module(_shared)
configure = _shared.configure


def validate_lab_database_target(directory):
    # Chặn việc trỏ Filer sang DB của Platform trước khi sinh bất kỳ secret nào.
    template = dotenv_values(directory / ".env.example")
    overrides = dotenv_values(directory / ".env")
    effective = {
        key: os.environ.get(key, overrides.get(key, value)) or ""
        for key, value in template.items()
    }
    if effective.get("FILER_DB_HOST") != "postgres" or effective.get("FILER_DB_PORT") != "5432":
        raise ValueError("Enterprise Lab phải dùng PostgreSQL container tại postgres:5432.")
    if "POSTGRES_SUPERUSER_PASSWORD" not in effective:
        raise ValueError("Thiếu cấu hình bootstrap PostgreSQL của Enterprise Lab.")


def main():
    directory = Path(__file__).resolve().parent
    try:
        validate_lab_database_target(directory)
        configure(directory)
    except (ValueError, OSError):
        raise SystemExit("Không tạo cấu hình: .local đã tồn tại hoặc dữ liệu đầu vào không hợp lệ. Không ghi đè secret.") from None
    print("Đã tạo cấu hình enterprise-local độc lập. Chưa chạy container hay chuyển dữ liệu.")


if __name__ == "__main__":
    main()
