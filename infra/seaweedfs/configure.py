"""Sinh cấu hình development; không thay backend/.env hoặc database đang dùng."""
import json
import os
import re
import secrets
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import dotenv_values
from psycopg import sql


def configure(directory):
    directory = Path(directory)
    local = directory / ".local"
    if local.exists():
        raise ValueError(".local đã tồn tại; giữ nguyên để tránh đổi secret của runtime hiện có.")
    template = dotenv_values(directory / ".env.example")
    existing = dotenv_values(directory / ".env")
    config = {key: os.environ.get(key, existing.get(key, value)) or "" for key, value in template.items()}
    for key in ("FILER_DB_NAME", "FILER_DB_USER"):
        if not re.fullmatch(r"[a-z][a-z0-9_]{2,62}", config[key]):
            raise ValueError("Tên database/role không hợp lệ.")
    if config["FILER_DB_NAME"] in {"postgres", "bluedrive_db", "securedrive", "template0", "template1"}:
        raise ValueError("Filer phải dùng database riêng.")
    if config["FILER_DB_USER"] in {"postgres", "securedrive_app"}:
        raise ValueError("Filer phải dùng role riêng.")
    for endpoint in ("SEAWEED_S3_ENDPOINT", "SEAWEED_S3_PUBLIC_ENDPOINT"):
        parsed = urlsplit(config[endpoint])
        if (parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "s3.localhost"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("Bộ sinh cấu hình này chỉ dành cho endpoint HTTP loopback development.")
    origins = config["FRONTEND_ORIGINS"].split(",")
    for origin in origins:
        parsed = urlsplit(origin)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.path
                or parsed.username or parsed.password or parsed.query or parsed.fragment or "*" in origin):
            raise ValueError("CORS cần danh sách origin cụ thể.")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,61}[a-z0-9]", config["SEAWEED_S3_BUCKET"]):
        raise ValueError("Tên bucket không hợp lệ.")
    if not config["FILER_DB_PORT"].isdigit() or not 1 <= int(config["FILER_DB_PORT"]) <= 65535:
        raise ValueError("Cổng PostgreSQL không hợp lệ.")
    if "POSTGRES_SUPERUSER_PASSWORD" in config and (config["FILER_DB_HOST"] != "postgres" or config["FILER_DB_PORT"] != "5432"):
        raise ValueError("Compose có PostgreSQL riêng; Filer phải dùng postgres:5432.")
    # Mỗi Compose project có mật khẩu bootstrap riêng; Filer không dùng tài khoản quản trị.
    secret_keys = ["FILER_DB_PASSWORD", "SEAWEED_S3_ACCESS_KEY", "SEAWEED_S3_SECRET_KEY", "SEAWEED_S3_ADMIN_ACCESS_KEY", "SEAWEED_S3_ADMIN_SECRET_KEY"]
    if "POSTGRES_SUPERUSER_PASSWORD" in config:
        secret_keys.append("POSTGRES_SUPERUSER_PASSWORD")
    for key in secret_keys:
        config[key] = config[key] or secrets.token_hex(32)
        if not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", config[key]):
            raise ValueError("Secret development phải dài tối thiểu 20 ký tự, chỉ dùng chữ/số/_/-.")
    if config.get("POSTGRES_SUPERUSER_PASSWORD") == config["FILER_DB_PASSWORD"]:
        raise ValueError("Mật khẩu bootstrap PostgreSQL và Filer phải riêng biệt.")
    if config["SEAWEED_S3_ACCESS_KEY"] == config["SEAWEED_S3_ADMIN_ACCESS_KEY"]:
        raise ValueError("Ứng dụng và operator phải dùng identity riêng.")

    bucket = config["SEAWEED_S3_BUCKET"]
    identities = {"identities": [
        {"name": "bluedrive-operator", "credentials": [{"accessKey": config["SEAWEED_S3_ADMIN_ACCESS_KEY"], "secretKey": config["SEAWEED_S3_ADMIN_SECRET_KEY"]}], "actions": ["Admin"]},
        {"name": "bluedrive-app", "credentials": [{"accessKey": config["SEAWEED_S3_ACCESS_KEY"], "secretKey": config["SEAWEED_S3_SECRET_KEY"]}], "actions": [f"{action}:{bucket}" for action in ("Read", "Write", "List", "Tagging")]},
    ]}
    filer = '[leveldb2]\nenabled = false\n\n[postgres]\nenabled = true\ncreateTable = false\nenableUpsert = true\n'
    for name, value in {"hostname": config["FILER_DB_HOST"], "port": int(config["FILER_DB_PORT"]),
                        "database": config["FILER_DB_NAME"], "username": config["FILER_DB_USER"],
                        "password": config["FILER_DB_PASSWORD"], "schema": "public", "sslmode": config["FILER_DB_SSLMODE"]}.items():
        filer += f"{name} = {json.dumps(value)}\n"
    db, role, password = (config[key] for key in ("FILER_DB_NAME", "FILER_DB_USER", "FILER_DB_PASSWORD"))
    bootstrap = "\\set ON_ERROR_STOP on\n"
    bootstrap += sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT;\n").format(sql.Identifier(role), sql.Literal(password)).as_string()
    bootstrap += sql.SQL("CREATE DATABASE {} OWNER {};\nREVOKE ALL ON DATABASE {} FROM PUBLIC;\n").format(sql.Identifier(db), sql.Identifier(role), sql.Identifier(db)).as_string()
    bootstrap += f"\\connect {db}\n"
    bootstrap += sql.SQL("REVOKE ALL ON SCHEMA public FROM PUBLIC;\nALTER SCHEMA public OWNER TO {};\nSET ROLE {};\n").format(sql.Identifier(role), sql.Identifier(role)).as_string()
    bootstrap += "CREATE TABLE filemeta (dirhash BIGINT, name VARCHAR(65535), directory VARCHAR(65535), meta BYTEA, PRIMARY KEY (dirhash, name));\nRESET ROLE;\n"
    cors = {"CORSRules": [{"AllowedOrigins": origins, "AllowedMethods": ["GET", "HEAD", "PUT", "POST", "DELETE"],
                           "AllowedHeaders": ["content-type", "content-md5", "range", "if-match", "x-amz-checksum-sha256", "x-amz-content-sha256", "x-amz-sdk-checksum-algorithm"],
                           "ExposeHeaders": ["ETag", "x-amz-checksum-sha256", "x-amz-checksum-type", "x-amz-version-id", "Content-Length", "Content-Range"], "MaxAgeSeconds": 300}]}
    backend = {"SECUREDRIVE_STORAGE_ENDPOINT_URL": config["SEAWEED_S3_ENDPOINT"],
               "SECUREDRIVE_STORAGE_PUBLIC_ENDPOINT_URL": config["SEAWEED_S3_PUBLIC_ENDPOINT"],
               "SECUREDRIVE_STORAGE_BUCKET": bucket, "SECUREDRIVE_STORAGE_REGION": "us-east-1",
               "SECUREDRIVE_STORAGE_ADDRESSING_STYLE": "path", "SECUREDRIVE_STORAGE_ACCESS_KEY_ID": config["SEAWEED_S3_ACCESS_KEY"],
               "SECUREDRIVE_STORAGE_SECRET_ACCESS_KEY": config["SEAWEED_S3_SECRET_KEY"],
               "SECUREDRIVE_DIRECT_DOWNLOAD_ENABLED": "false"}
    local.mkdir(mode=0o700)
    files = {"filer.toml": filer, "s3.json": json.dumps(identities, indent=2), "cors.json": json.dumps(cors, indent=2),
             "bootstrap.sql": bootstrap, "backend.env": "".join(f"{key}={value}\n" for key, value in backend.items())}
    for name, value in files.items():
        target = local / name
        target.write_text(value, encoding="utf-8")
        target.chmod(0o600)
    env_path = directory / ".env"
    env_path.write_text("".join(f"{key}={value}\n" for key, value in config.items()), encoding="utf-8")
    env_path.chmod(0o600)
    return config


if __name__ == "__main__":
    try:
        configure(Path(__file__).resolve().parent)
    except (ValueError, OSError):
        raise SystemExit("Không sinh cấu hình: kiểm tra đầu vào hoặc .local đã tồn tại. Giữ nguyên cấu hình hiện có.") from None
    print("Đã sinh cấu hình local. Chưa provision PostgreSQL, chưa đổi backend/.env, chưa cutover.")
