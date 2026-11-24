# Copyright (c) iGroup China.
# All rights reserved.
"""
TLS CA 证书兜底（PyInstaller 单文件）。

@author Kai
@date 2026/09/16 11:42
@description 单文件 exe 会把 certifi 解压到 Temp\\_MEI*；托盘常驻后
    Windows/杀毒可能清掉该目录，requests 随即找不到 cacert.pem。
    启动时把证书拷到 exe 旁并改写 certifi/requests 的查找路径。
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Optional

# 已成功绑定的 CA 包路径；空串表示尚未初始化
_BOUND_BUNDLE = ""
# 证书文件至少应大于该体积，避免拷到空文件
_MIN_BUNDLE_BYTES = 10_000


def ca_bundle_path() -> Path:
    """
    持久化 CA 证书存放路径（exe 旁，不被 Temp 清理）。

    @return cacert.pem 目标路径
    @author Kai
    @date 2026/09/16 11:42
    """
    from .paths import ROOT

    return ROOT / "certs" / "cacert.pem"


def _is_valid_bundle(path: Path) -> bool:
    """
    判断路径是否为可用的 CA 证书包。

    @param path 候选文件路径
    @return 文件存在且体积足够时为 True
    @author Kai
    @date 2026/09/16 11:42
    """
    try:
        return path.is_file() and path.stat().st_size >= _MIN_BUNDLE_BYTES
    except OSError:
        return False


def _discover_source() -> Optional[Path]:
    """
    按优先级寻找一份仍可读的 cacert.pem。

    @return 源文件路径；都找不到时返回 None
    @author Kai
    @date 2026/09/16 11:42
    """
    from .paths import ROOT, is_frozen, resource_root

    candidates: list[Path] = [ca_bundle_path(), ROOT / "cacert.pem"]
    # 用户或运维预先指定的环境变量
    for key in ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            candidates.append(Path(raw))
    try:
        import certifi

        candidates.append(Path(certifi.where()))
    except Exception:
        pass
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        mei = Path(getattr(sys, "_MEIPASS"))
        candidates.append(mei / "certifi" / "cacert.pem")
    candidates.append(resource_root() / "certifi" / "cacert.pem")

    seen: set[str] = set()
    for item in candidates:
        key = str(item)
        if key in seen:
            continue
        seen.add(key)
        if _is_valid_bundle(item):
            return item
    return None


def _bind_bundle(bundle: str) -> None:
    """
    让 ssl / certifi / requests 都改用持久化证书路径。

    @param bundle 已落盘的 cacert.pem 绝对路径
    @author Kai
    @date 2026/09/16 11:42
    """
    os.environ["SSL_CERT_FILE"] = bundle
    os.environ["REQUESTS_CA_BUNDLE"] = bundle
    os.environ["CURL_CA_BUNDLE"] = bundle

    def _where() -> str:
        return bundle

    try:
        import certifi
        import certifi.core as certifi_core

        certifi.where = _where
        certifi_core.where = _where
        certifi_core._CACERT_PATH = bundle
    except Exception:
        pass

    # requests 在 import 时会把 certifi.where() 缓存进常量，必须两边一起改
    for mod_name in ("requests.utils", "requests.adapters", "requests.certs"):
        mod = sys.modules.get(mod_name)
        if mod is None:
            continue
        try:
            if hasattr(mod, "DEFAULT_CA_BUNDLE_PATH"):
                setattr(mod, "DEFAULT_CA_BUNDLE_PATH", bundle)
            if hasattr(mod, "where"):
                setattr(mod, "where", _where)
        except Exception:
            pass


def ensure_ca_bundle() -> str:
    """
    确保 HTTPS 使用一份不会被 Temp 清理的 CA 证书。

    开发态只绑定 certifi 自带路径；打包态再拷到 exe 旁的 certs\\cacert.pem。

    @return 实际使用的证书路径；找不到时返回空串
    @author Kai
    @date 2026/09/16 11:42
    """
    global _BOUND_BUNDLE
    from .paths import LOG, is_frozen

    if _BOUND_BUNDLE and _is_valid_bundle(Path(_BOUND_BUNDLE)):
        _bind_bundle(_BOUND_BUNDLE)
        return _BOUND_BUNDLE

    source = _discover_source()
    if source is None:
        LOG.warning(
            "TLS CA 证书缺失，HTTPS 将失败。请重启应用；"
            "若刚升级请重新打包并确保带上 certifi"
        )
        return ""

    bundle_path = source
    if is_frozen():
        dest = ca_bundle_path()
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.resolve() != dest.resolve():
                # 源更新或目标损坏时覆盖；已有完好副本则直接复用
                if not _is_valid_bundle(dest) or source.stat().st_mtime > dest.stat().st_mtime:
                    shutil.copy2(source, dest)
            if _is_valid_bundle(dest):
                bundle_path = dest
        except OSError as exc:
            LOG.warning("无法持久化 CA 证书，回退源文件: %s", exc)

    bundle = str(bundle_path.resolve())
    _bind_bundle(bundle)
    _BOUND_BUNDLE = bundle
    if source.resolve() != bundle_path.resolve():
        LOG.info("TLS CA 证书已持久化 path=%s", bundle)
    return bundle
