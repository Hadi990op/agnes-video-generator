#!/usr/bin/env python3
"""Auto-configure GA4 for agnes-video-generator analytics.

Automates the parts of GA4 setup that the Admin API supports:
  1. Register custom event-scoped dimensions (task_type, mode, resolution, ...)
  2. Mark key events (conversions): create_task, task_completed

NOT automated (Google Admin API does not support it):
  - Explore reports (must be created manually in the GA4 UI)

Usage:
  # Install dependency once:
  #   pip install google-analytics-admin

  # Dry run (no changes):
  #   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  #   python3 scripts/setup_ga4.py --property-id 123456789 --dry-run

  # Apply:
  #   GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json \
  #   python3 scripts/setup_ga4.py --property-id 123456789

Prerequisites (one-time, done in Google Cloud / GA4 UI):
  1. Google Cloud Console → APIs & Services → enable "Google Analytics Admin API"
  2. Create a service account, download its JSON key
  3. GA4 → Admin → Property access management → add the service account email
     as "Viewer" (Viewer is enough; GA4 grants change rights automatically
     to the service account owner for admin tasks) — if creation fails with
     PERMISSION_DENIED, grant "Administrator" and retry.
"""

import argparse
import os
import sys

# GA4 事件参数 → (自定义维度展示名, 事件作用域)
# 与 static/index.html 中 trackEvent / reportException 上报的参数一一对应。
CUSTOM_DIMENSIONS = [
    # 任务创建 / 结果通用
    ("task_type", "任务类型"),
    ("mode", "简单视频模式"),
    ("resolution", "分辨率"),
    ("duration", "时长"),
    ("scene_count", "场景数"),
    ("audio_source", "音频来源"),
    # 配置操作
    ("action", "配置动作"),
    # 报错
    ("error", "错误信息"),
    ("description", "异常描述"),
    ("fatal", "是否致命"),
]

# 需要标记为关键事件（转化）的自定义事件
KEY_EVENTS = [
    "create_task",
    "task_completed",
]


def build_client():
    try:
        from google.analytics.admin_v1beta import AnalyticsAdminServiceClient
    except ImportError:
        sys.exit(
            "缺少依赖 google-analytics-admin。请先运行：\n"
            "  pip install google-analytics-admin\n"
            "并使用 GOOGLE_APPLICATION_CREDENTIALS 指向服务账号 JSON。"
        )
    return AnalyticsAdminServiceClient()


def run(property_id: str, dry_run: bool) -> int:
    from google.analytics.admin_v1beta.types import CustomDimension, KeyEvent

    client = build_client()
    parent = f"properties/{property_id}"
    print(f"目标资源：{parent}\n")

    # ── 1. 自定义维度 ──────────────────────────────────────────────
    print("== 自定义维度 ==")
    existing = {}
    try:
        for dim in client.list_custom_dimensions(parent=parent):
            existing[dim.parameter_name] = dim.display_name
    except Exception as e:
        print(f"[!] 读取现有维度失败：{e}")
        print("    请确认：Property ID 正确、Admin API 已启用、服务账号已授权。")
        return 1

    created = 0
    for param, display in CUSTOM_DIMENSIONS:
        if param in existing:
            print(f"  [skip] {param}（已存在：{existing[param]}）")
            continue
        if dry_run:
            print(f"  [dry]  将创建维度 {param}（{display}）")
            continue
        try:
            client.create_custom_dimension(
                parent=parent,
                custom_dimension=CustomDimension(
                    parameter_name=param,
                    display_name=display,
                    scope=CustomDimension.Scope.SCOPE_EVENT,
                ),
            )
            created += 1
            print(f"  [ok]   创建维度 {param}（{display}）")
        except Exception as e:
            print(f"  [fail] 创建维度 {param} 失败：{e}")

    # ── 2. 关键事件 ────────────────────────────────────────────────
    print("\n== 关键事件（转化）==")
    existing_keys = set()
    try:
        for ke in client.list_key_events(parent=parent):
            existing_keys.add(ke.event_name)
    except Exception as e:
        print(f"[!] 读取现有关键事件失败：{e}")
        return 1

    created_keys = 0
    for name in KEY_EVENTS:
        if name in existing_keys:
            print(f"  [skip] {name}（已标记为关键事件）")
            continue
        if dry_run:
            print(f"  [dry]  将标记关键事件 {name}")
            continue
        try:
            client.create_key_event(
                parent=parent,
                key_event=KeyEvent(event_name=name),
            )
            created_keys += 1
            print(f"  [ok]   标记关键事件 {name}")
        except Exception as e:
            print(f"  [fail] 标记关键事件 {name} 失败：{e}")

    print(f"\n完成：新增维度 {created} 个，新增关键事件 {created_keys} 个。")
    if dry_run:
        print("（dry-run 模式，未做任何修改；去掉 --dry-run 即可生效）")
    return 0


def main():
    parser = argparse.ArgumentParser(description="自动配置 GA4 自定义维度与关键事件")
    parser.add_argument(
        "--property-id",
        required=True,
        help="GA4 媒体资源 ID（GA4 后台 → 管理 → 数据流 → 显示为数字）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅预览将要创建的项目，不实际修改",
    )
    args = parser.parse_args()

    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        parser.error(
            "请设置 GOOGLE_APPLICATION_CREDENTIALS 环境变量指向服务账号 JSON，"
            "例如：GOOGLE_APPLICATION_CREDENTIALS=/path/to/sa.json"
        )
    sys.exit(run(args.property_id, args.dry_run))


if __name__ == "__main__":
    main()
