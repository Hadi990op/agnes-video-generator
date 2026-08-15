#!/usr/bin/env python3
"""多语言完整性检查脚本。

检查 frontend/src/i18n/translations.ts 中所有语言相对 zh（基准语言）的 key 缺失。
- 任何语言缺失 → 打印缺失清单并返回非零退出码（回归脚本据此停止）
- 全部完整 → 返回 0

用法:
    python scripts/i18n_check.py          # 全量检查（退出码 0/1）
    python scripts/i18n_check.py --json   # 输出 JSON（缺失映射）
"""

import argparse
import json
import re
import sys
from pathlib import Path

# 基准语言：所有其他语言的 key 集合必须覆盖 zh 的 key 集合
BASE_LANG = 'zh'

# 允许语言区块内出现但 zh 没有的孤立 key（历史遗留，勿新增）
ALLOWED_EXTRA = {'project'}


def parse_translations(path: Path) -> dict[str, set[str]]:
    """解析 translations.ts，返回 {lang: set(keys)}。"""
    content = path.read_text(encoding='utf-8')
    lang_start = list(re.finditer(r'^  (\w+): \{', content, re.M))
    if not lang_start:
        raise ValueError(f'{path} 中未找到语言区块')
    blocks: dict[str, str] = {}
    for i, m in enumerate(lang_start):
        end = lang_start[i + 1].start() if i + 1 < len(lang_start) else len(content)
        blocks[m.group(1)] = content[m.start():end]

    result: dict[str, set[str]] = {}
    for lang, block in blocks.items():
        keys = set(re.findall(r"(?:^|\s|,)([A-Za-z_]\w*):\s*'", block, re.M))
        result[lang] = keys
    return result


def check(path: Path) -> dict[str, list[str]]:
    """返回 {lang: 缺失 key 列表}；空 dict 表示完整。"""
    langs = parse_translations(path)
    base = langs.get(BASE_LANG)
    if base is None:
        raise ValueError(f'缺少基准语言 {BASE_LANG}')
    missing: dict[str, list[str]] = {}
    for lang, keys in langs.items():
        if lang == BASE_LANG:
            continue
        diff = sorted(base - keys)
        if diff:
            missing[lang] = diff
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description='多语言完整性检查')
    parser.add_argument('--path', default='frontend/src/i18n/translations.ts',
                        help='translations.ts 路径（相对项目根目录）')
    parser.add_argument('--json', action='store_true', help='输出 JSON 格式')
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f'[i18n_check] 文件不存在: {path}', file=sys.stderr)
        return 2

    try:
        missing = check(path)
    except ValueError as e:
        print(f'[i18n_check] 解析失败: {e}', file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(missing, ensure_ascii=False, indent=2))
    else:
        if missing:
            print('[i18n_check] ❌ 多语言缺失，需补齐后再继续：')
            for lang, keys in sorted(missing.items()):
                print(f'  {lang}: 缺失 {len(keys)} 个 key → {keys[:8]}{"..." if len(keys) > 8 else ""}')
        else:
            print('[i18n_check] ✅ 多语言完整，无缺失')

    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main())
