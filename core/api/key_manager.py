"""core.api.key_manager — 多 API Key 统一轮换（KeyRing 单例）

职责：
1. 基于 get_api_keys() 惰性初始化；Key 变更后 reset_key_ring() 重建
2. next(): 普通请求轮转（round-robin，原子计数，均匀分摊配额）
3. rotate(): 429 时强制切到下一个 Key（供换 Key 重试）
4. has_multiple() / __len__: 供限速器配额与重试策略判断

用法::

    from core.api.key_manager import get_key_ring, reset_key_ring

    key = get_key_ring().next()
    get_key_ring().rotate()   # 429 换 Key
"""
import itertools
import logging
import threading

from core.config import get_api_keys

logger = logging.getLogger(__name__)


class KeyRing:
    def __init__(self, keys: list):
        if not keys:
            raise ValueError("KeyRing requires at least one key")
        self._keys = list(keys)
        self._count = itertools.count()
        self._lock = threading.Lock()

    def next(self) -> str:
        """轮转取下一个 Key（普通请求调用，均匀分摊）。"""
        return self._keys[next(self._count) % len(self._keys)]

    def rotate(self) -> str:
        """强制切换到下一个 Key（429 换 Key 重试调用）。"""
        with self._lock:
            idx = next(self._count) % len(self._keys)
            return self._keys[idx]

    @property
    def keys(self) -> list:
        return list(self._keys)

    def has_multiple(self) -> bool:
        return len(self._keys) > 1

    def __len__(self) -> int:
        return len(self._keys)

    def describe(self) -> str:
        """日志用：key#2/3 等。"""
        return f"key#{next(self._count) % len(self._keys) + 1}/{len(self._keys)}"


_instance: KeyRing | None = None
_lock = threading.Lock()


def get_key_ring() -> KeyRing:
    """获取全局 KeyRing（线程安全单例，惰性初始化）。"""
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                keys = get_api_keys()
                if not keys:
                    raise RuntimeError(
                        "No Agnes API Key configured (AGNES_API_KEY or config api_key)"
                    )
                _instance = KeyRing(keys)
                logger.info(f"[KeyManager] KeyRing 初始化: {len(keys)} 个 Key")
    return _instance


def reset_key_ring() -> None:
    """Key 变更后重建 KeyRing（配合 set_api_keys / delete_api_key）。"""
    global _instance
    with _lock:
        _instance = None


def _reset_and_reload() -> KeyRing:
    """重建 KeyRing 并返回新实例（供 set_api_keys 后调用）。"""
    reset_key_ring()
    return get_key_ring()
