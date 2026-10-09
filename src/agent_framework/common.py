"""Small shared primitives. All state writers use these deterministic encodings."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
from typing import Any, Iterator


class FrameworkError(Exception):
    """A user-actionable contract, integrity or infrastructure failure."""


class Conflict(FrameworkError):
    """An optimistic revision/precondition no longer matches."""


class IntegrityError(FrameworkError):
    """Recorded content or an immutable binding is inconsistent."""


class LeaseRetained(FrameworkError):
    """An execution may still exist; its lease requires explicit recovery."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def canonical(value: Any) -> bytes:
    """Encoder v1: sorted Unicode keys, UTF-8, compact JSON, no NaN/Infinity."""

    def check(item: Any) -> None:
        if isinstance(item, dict):
            if any(not isinstance(k, str) for k in item):
                raise FrameworkError("canonical JSON object keys must be strings")
            for child in item.values():
                check(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                check(child)

    check(value)
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FrameworkError(f"value is not canonical JSON: {exc}") from exc


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def bytes_digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for k, v in pairs:
        if k in value:
            raise FrameworkError(f"duplicate JSON key: {k}")
        value[k] = v
    return value


def decode(raw: bytes | str) -> Any:
    try:
        return json.loads(
            raw,
            object_pairs_hook=_pairs,
            parse_constant=lambda v: (_ for _ in ()).throw(
                FrameworkError(f"invalid number: {v}")
            ),
        )
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise FrameworkError(f"invalid JSON: {exc}") from exc


def read_json(path: Path) -> Any:
    try:
        return decode(path.read_bytes())
    except OSError as exc:
        raise FrameworkError(f"cannot read {path}: {exc}") from exc


def atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            os.fchmod(f.fileno(), mode)
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        Path(name).unlink(missing_ok=True)


def write_json(path: Path, value: Any, mode: int = 0o600) -> None:
    atomic_write(path, canonical(value) + b"\n", mode)


def identifier(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{1,95}", value):
        raise FrameworkError(f"invalid identifier: {value!r}")
    return value


def sha(value: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:[a-f0-9]{40}|[a-f0-9]{64})", value
    ):
        raise FrameworkError("invalid immutable Git/artifact identity")
    return value


def safe_relative(value: str) -> str:
    if not isinstance(value, str):
        raise FrameworkError("relative path must be a string")
    p = PurePosixPath(value)
    if (
        not value
        or p.is_absolute()
        or ".." in p.parts
        or "\\" in value
        or "\x00" in value
        or any(ord(c) < 32 for c in value)
    ):
        raise FrameworkError(f"unsafe relative path: {value!r}")
    if str(p) in (".", ""):
        raise FrameworkError("empty relative path")
    if str(p) != value:
        raise FrameworkError("relative paths must use their canonical spelling")
    return p.as_posix()


def contained(root: Path, relative: str, *, reject_symlinks: bool = True) -> Path:
    relative = safe_relative(relative)
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise FrameworkError(f"path leaves its approved root: {relative}")
    if reject_symlinks:
        current = root
        for part in PurePosixPath(relative).parts:
            current /= part
            if current.is_symlink():
                raise FrameworkError(
                    f"symlink is not an approved input/output: {relative}"
                )
    return path


@contextmanager
def locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
