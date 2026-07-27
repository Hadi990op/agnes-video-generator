"""单元测试：core.path_security —— 路径穿越防护。

验证 safe_join / safe_workspace_path 在受信任根内正常拼接，
对越界（路径遍历）输入抛 UnsafePathError。
纯逻辑、不依赖网络/ffmpeg，秒级运行。
"""
import os

import pytest

from core.path_security import (
    UnsafePathError,
    safe_join,
    safe_workspace_path,
)


def test_safe_join_normal_nested(tmp_path):
    root = str(tmp_path)
    result = safe_join(root, "a", "b", "c.txt")
    assert result == os.path.join(os.path.realpath(root), "a", "b", "c.txt")


def test_safe_join_empty_parts_returns_root(tmp_path):
    # 无 parts：结果应等于 root 自身（边界允许）
    root = str(tmp_path)
    assert safe_join(root) == os.path.realpath(root)


def test_safe_join_dot_stays_in_root(tmp_path):
    root = str(tmp_path)
    assert safe_join(root, ".") == os.path.realpath(root)


def test_safe_join_traversal_escapes_root(tmp_path):
    root = str(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_join(root, "..", "..", "etc", "passwd")


def test_safe_join_traversal_within_filename(tmp_path):
    root = str(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_join(root, "sub", "..", "..", "secret")


def test_safe_workspace_path_normal(tmp_path):
    root = str(tmp_path)
    result = safe_workspace_path("sub/dir/file.txt", allowed_root=root)
    assert result == os.path.join(os.path.realpath(root), "sub", "dir", "file.txt")


def test_safe_workspace_path_traversal_rejected(tmp_path):
    root = str(tmp_path)
    with pytest.raises(UnsafePathError):
        safe_workspace_path("../../etc/passwd", allowed_root=root)


def test_safe_workspace_path_default_root_allows_absolute(tmp_path):
    # 默认根 = 文件系统根 "/"，任何绝对路径都被允许
    # （符合设计：放行操作员通过系统对话框自选的任意目录）
    abs_target = os.path.realpath("/tmp")
    result = safe_workspace_path(abs_target)
    assert result == abs_target


def test_unsafe_path_error_is_value_error():
    assert issubclass(UnsafePathError, ValueError)
