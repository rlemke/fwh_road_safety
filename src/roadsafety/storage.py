"""Backend-aware paths for the road-safety domain.

A thin shim over ``facetwork.domains.storage`` — the shared layer owns the
behaviour; this keeps the import path and public names.
"""
from __future__ import annotations

from facetwork.domains.storage import domain_storage, is_remote, join  # noqa: F401

_S = domain_storage("road_safety", path_name="road-safety", local_name="road-safety")


def data_root() -> str:
    return _S.data_root()


_data_root = data_root


def cache_root() -> str:
    return _S.cache_root()


def output_root() -> str:
    return _S.output_root()


def maps_root() -> str:
    return _S.maps_root()


def exists(path: str) -> bool:
    return _S.exists(path)


def localize(path: str) -> str:
    return _S.localize(path)


def read_text(path: str) -> str:
    return _S.read_text(path)


def write_text(path: str, body: str) -> None:
    _S.write_text(path, body)


def read_bytes(path: str) -> bytes:
    return _S.read_bytes(path)


def write_bytes(path: str, body: bytes) -> None:
    _S.write_bytes(path, body)


def open_read(path: str, mode: str = "r", **kw):
    return _S.open_read(path, mode, **kw)


def open_write(path: str, mode: str = "w", **kw):
    return _S.open_write(path, mode, **kw)
