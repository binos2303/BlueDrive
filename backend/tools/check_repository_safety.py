"""Kiểm tra source/index Git; không mở file private hoặc in giá trị nhạy cảm."""
import argparse
import json
import re
import subprocess
from pathlib import Path


SECRET_NAME = re.compile(r"(?:PASSWORD|TOKEN|SECRET(?:_?KEY)?|PEPPER|(?:API|ACCESS|AES)_?KEY(?:_ID)?)$", re.I)
ASSIGNMENT = re.compile(r'''^\s*(?:export\s+)?["']?([A-Za-z_][A-Za-z0-9_]*)["']?\s*[:=]\s*(.*)$''')
PLACEHOLDER = re.compile(r"^(?:<[^<>]+>|\$\{[A-Z_][A-Z0-9_]*(?::\?[^}]*)?\}|\$\{\{\s*secrets\.[A-Za-z0-9_]+\s*\}\})$")
CI_TEST_PASSWORD = re.compile(r"^\$\{\{\s*github\.run_id\s*\}\}-\$\{\{\s*github\.run_attempt\s*\}\}$")
PATTERNS = {
    "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    "provider-token": re.compile(r"\b(?:sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}|gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})\b"),
    "aws-access-key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "signed-url": re.compile(r'''https?://[^\s<>"']*[?&]X-Amz-Signature=[a-fA-F0-9]{32,}''', re.I),
    "database-dump": re.compile(r"^-- (?:PostgreSQL|MySQL) (?:database )?dump", re.M),
}
URL_PASSWORD = re.compile(r'''[a-z][a-z0-9+.-]*://[^\s/:@]+:([^\s/@]+)@''', re.I)
PRIVATE_SUFFIXES = (".dump", ".pgdump", ".backup", ".bak", ".sql.gz", ".dump.gz", ".p12", ".pfx", ".pem", ".key")


def private_path(name):
    """Chặn theo tên trước khi đọc, kể cả file được force-add vào Git."""
    normalized = name.lower()
    parts = normalized.split("/")
    basename = parts[-1]
    return (
        (basename.startswith(".env") and basename != ".env.example")
        or normalized.endswith(PRIVATE_SUFFIXES)
        or basename in {"credentials.json", "secrets.json", "id_rsa", "id_ed25519"}
        or any(part in {".aws", ".ssh", ".auth"} for part in parts)
        or normalized.startswith(("infra/seaweedfs/.local/", "backups/", "backend/backups/", "secrets/"))
        or bool(re.search(r"(?:^|/)(?:backup[^/]*|dump[^/]*|[^/]+[_-](?:backup|dump))\.sql$", name, re.I))
    )


def placeholder(value):
    value = value.strip().strip("\"'")
    # Giá trị CI này được tạo theo lượt chạy, không phải credential literal trong source.
    return not value or bool(PLACEHOLDER.fullmatch(value) or CI_TEST_PASSWORD.fullmatch(value))


def scan_text(name, content):
    """Chỉ trả loại phát hiện/vị trí; không trả đoạn source hoặc credential."""
    findings = []
    fixture = any(part.startswith("test_") or part == "tests" for part in Path(name).parts) or bool(re.search(r"(?:^tests\.py$|\.test\.[^.]+$)", Path(name).name))
    template = Path(name).name == ".env.example"
    suffix = Path(name).suffix.lower()
    config = template or suffix in {".yml", ".yaml", ".toml", ".json"}
    source = suffix in {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"}
    for line_number, line in enumerate(content.splitlines(), 1):
        for kind, pattern in PATTERNS.items():
            if pattern.search(line):
                findings.append({"path": name, "line": line_number, "kind": kind})
        # Bài kiểm tra từ chối URL có userinfo dùng sentinel giả; không miễn trừ URL khác.
        if any(not placeholder(match[1]) and not (fixture and match[1] in {"password", "secret", "test", "dummy"})
               for match in URL_PASSWORD.finditer(line)):
            findings.append({"path": name, "line": line_number, "kind": "url-password"})
        assignment = ASSIGNMENT.match(line)
        if assignment and SECRET_NAME.search(assignment[1]):
            raw = assignment[2].strip()
            literal = re.match(r'''(["'])([^"'\r\n]*)\1''', raw)
            value = literal[2] if literal else raw.split(" #", 1)[0].strip()
            # Dict label của form không phải phép gán credential; config vẫn kiểm tra key/value.
            quoted_mapping = line.lstrip().startswith(("'", '"'))
            if (config or (source and literal and not fixture and not quoted_mapping)) and not placeholder(value):
                findings.append({"path": name, "line": line_number, "kind": "credential-literal"})
    return findings


def git(root, *args, input=None):
    result = subprocess.run(["git", "-C", str(root), *args], input=input, capture_output=True)
    if result.returncode:
        raise RuntimeError("Git operation unavailable")
    return result.stdout


def decode_source(content):
    if content.startswith((b"\xff\xfe", b"\xfe\xff")):
        return content.decode("utf-16")
    if b"\0" in content:
        return None
    return content.decode("utf-8-sig", errors="replace")


def audit(root, *, staged=False):
    root = Path(root).resolve()
    names = set(git(root, "ls-files", "--cached", "-z").decode("utf-8").split("\0"))
    if not staged:
        names.update(git(root, "ls-files", "--others", "--exclude-standard", "-z").decode("utf-8").split("\0"))
    findings, blocked, checked, binary = [], [], 0, 0
    for name in sorted(names - {""}):
        if private_path(name):
            findings.append({"path": name, "line": 0, "kind": "private-artifact"})
            continue
        try:
            if staged:
                content = git(root, "show", ":" + name)
            else:
                path = root / name
                if path.is_symlink() or not path.resolve().is_relative_to(root):
                    blocked.append({"path": name, "kind": "uninspected-link"})
                    continue
                if not path.exists():
                    continue  # File đã xóa trong working tree không phải một lần đọc thất bại.
                content = path.read_bytes()
            if content.startswith(b"PGDMP"):
                findings.append({"path": name, "line": 0, "kind": "database-dump"})
                continue
            text = decode_source(content)
            if text is None:
                binary += 1
                continue
            checked += 1
            findings.extend(scan_text(name, text))
        except (OSError, ValueError, RuntimeError):
            blocked.append({"path": name, "kind": "unreadable-source"})
    status = "FAIL" if findings else "BLOCKED" if blocked else "PASS"
    return {"status": status, "scope": "index" if staged else "working-tree", "text_files": checked,
            "binary_files_not_scanned": binary, "findings": findings, "blocked": blocked}


def audit_history(root, *, ref=None):
    """Quét commit reachable local; không mở blob private, không fetch hoặc sửa ref/index."""
    root = Path(root).resolve()
    revisions = ["--all"] if ref is None else [git(root, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()]
    commits = git(root, "rev-list", *revisions).decode().splitlines()
    shallow = git(root, "rev-parse", "--is-shallow-repository").strip() == b"true"
    aliases = {}
    for commit in commits:
        for entry in git(root, "ls-tree", "-r", "-z", "--full-tree", commit).split(b"\0"):
            if not entry:
                continue
            metadata, name = entry.split(b"\t", 1)
            mode, kind, oid = metadata.decode().split()
            if kind == "blob":
                aliases.setdefault(oid, {}).setdefault(name.decode("utf-8"), (commit, mode))
    findings, blocked, readable = [], [], {}
    for oid, paths in aliases.items():
        private = [name for name in paths if private_path(name)]
        for name in private:
            findings.append({"path": name, "line": 0, "kind": "private-artifact", "blob": oid[:12], "seen_in_commit": paths[name][0][:12]})
        # Một blob có alias private thì không đọc, kể cả alias khác trông như source thường.
        if private:
            continue
        if any(mode == "120000" for _, mode in paths.values()):
            blocked.append({"blob": oid[:12], "kind": "uninspected-link"})
            continue
        readable[oid] = paths
    checked = binary = 0
    payload = git(root, "cat-file", "--batch", input=("\n".join(readable) + "\n").encode()) if readable else b""
    offset = 0
    for oid, paths in readable.items():
        end = payload.index(b"\n", offset)
        header = payload[offset:end].decode().split()
        if len(header) != 3 or header[:2] != [oid, "blob"]:
            raise RuntimeError("Invalid Git object stream")
        size = int(header[2])
        content = payload[end + 1:end + 1 + size]
        offset = end + 2 + size
        if len(content) != size or payload[offset - 1:offset] != b"\n":
            raise RuntimeError("Incomplete Git object stream")
        try:
            text = decode_source(content)
            if text is None and not content.startswith(b"PGDMP"):
                binary += 1
                continue
            checked += 1
            for name, (commit, _) in paths.items():
                matches = [{"path": name, "line": 0, "kind": "database-dump"}] if content.startswith(b"PGDMP") else scan_text(name, text)
                findings.extend(dict(item, blob=oid[:12], seen_in_commit=commit[:12]) for item in matches)
        except UnicodeError:
            blocked.append({"blob": oid[:12], "kind": "unreadable-source"})
    if shallow or not commits:
        blocked.append({"kind": "shallow-history" if shallow else "empty-history"})
    return {"status": "FAIL" if findings else "BLOCKED" if blocked else "PASS", "scope": "local-history",
            "ref": ref or "all-local-refs", "commits": len(commits), "unique_blobs": len(aliases),
            "text_blobs": checked, "binary_blobs_not_scanned": binary, "findings": findings, "blocked": blocked}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--staged", action="store_true", help="Kiểm tra toàn bộ nội dung index, không chỉ working tree.")
    modes.add_argument("--history", nargs="?", const="--all", metavar="REF", help="Quét lịch sử reachable local; mặc định mọi ref, hoặc chỉ REF đã chỉ định.")
    args = parser.parse_args()
    try:
        root = Path(__file__).resolve().parents[2]
        report = audit_history(root, ref=None if args.history == "--all" else args.history) if args.history is not None else audit(root, staged=args.staged)
    except (OSError, RuntimeError, UnicodeError, ValueError):
        report = {"status": "BLOCKED", "reason": "Cannot enumerate Git source safely"}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return {"PASS": 0, "FAIL": 1, "BLOCKED": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
