"""
Batch 6（S12）路由层集成测试 — tests/test_routes.py

用 FastAPI TestClient 直接挂载 Batch 1 拆分出的 router（不经 server.py 启动），
覆盖（6.3 验收项）：
- config 路由：GET/POST/DELETE /api/config（API Key 脱敏 / env 来源保护 / 写入走 patch）
- workspaces 路由：列表 / 创建（空路径 422、非法路径 422）/ 删除（不存在 404）/ 激活
- voices 路由：GET /api/voices 目录结构、/api/voices/compat 兼容性查询
- task_creation 路由：5 个任务端点参数校验矩阵（400/422）+ 合法创建（pipeline 工厂、
  后台任务、TaskManager 全部打桩，不触网不写盘）+ 向后兼容旧端点 + 诗词 prompt 端点

写路径隔离原则：config 写入函数、workspace 配置函数、pipeline 工厂、后台任务启动、
TaskManager 均在 fixture 中打桩/定向到 tmp_path，测试绝不触碰真实配置与工作区。

用法:
    .venv/bin/python -m pytest tests/test_routes.py -v
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from core.path_security import UnsafePathError
from web.routes import config_routes, task_creation_routes, voice_routes, workspace_routes


# ═══════════════════════════════════════════════
# 共享 fixture：组装 app + 写路径隔离
# ═══════════════════════════════════════════════

@pytest.fixture(scope="module")
def client():
    """仅挂载待测 router 的独立 app（不加载 server.py）。"""
    app = FastAPI()
    app.include_router(config_routes.router)
    app.include_router(workspace_routes.router)
    app.include_router(voice_routes.router)
    app.include_router(task_creation_routes.router)
    return TestClient(app)


class _StubTaskManager:
    """打桩 TaskManager：只记录 state，不落盘。"""

    def __init__(self, task_id, dir_name=None):
        self.task_id = task_id
        self.state = None

    def create(self, state):
        self.state = state


@pytest.fixture
def task_env(monkeypatch, tmp_path):
    """任务创建端点的写路径隔离：
    - get_api_key → 固定测试 key（需要无 key 场景时单独 monkeypatch 覆盖）
    - pipeline 工厂 → 返回占位对象
    - launch_background_task → 只收集 coro，不真正调度
    - TaskManager → 内存 stub，不写磁盘
    """
    monkeypatch.setattr(task_creation_routes, "get_api_key", lambda: "test-api-key")

    monkeypatch.setattr(
        task_creation_routes.deps,
        "create_pipeline_for_type",
        lambda task_type, api_key, task_id, dir_name: object(),
    )

    launched = []

    def fake_launch(coro):
        launched.append(coro)
        coro.close()  # 测试不真正调度后台任务；close 避免 coroutine never awaited 警告

    monkeypatch.setattr(task_creation_routes.app_state, "launch_background_task", fake_launch)
    monkeypatch.setattr(task_creation_routes, "TaskManager", _StubTaskManager)
    return launched


# ═══════════════════════════════════════════════
# 1. config 路由
# ═══════════════════════════════════════════════

class TestConfigRoutes:
    def test_get_config_masks_api_key(self, client, monkeypatch):
        """GET /api/config：API Key 脱敏为前 8 字符 + ...，含工作区/水印/域名结构。"""
        monkeypatch.setattr(config_routes, "get_api_key", lambda: "abcdefghijklmnop")
        monkeypatch.setattr(config_routes, "get_api_key_source", lambda: "config")
        monkeypatch.setattr(config_routes, "get_workspaces", lambda: ["/tmp/ws1"])
        monkeypatch.setattr(config_routes, "get_active_workspace", lambda: "/tmp/ws1")
        monkeypatch.setattr(config_routes, "get_selected_models", lambda: {"text": "agnes-2.0-flash"})
        monkeypatch.setattr(config_routes, "get_agnes_domain", lambda: "com")

        resp = client.get("/api/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["api_key"] == "abcdefgh..."
        assert data["source"] == "config"
        assert data["workspaces"] == ["/tmp/ws1"]
        assert data["active_workspace"] == "/tmp/ws1"
        assert data["models"] == {"text": "agnes-2.0-flash"}
        assert data["agnes_domain"] == "com"
        assert isinstance(data["watermark"], dict)

    def test_get_config_empty_key(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_api_key", lambda: "")
        resp = client.get("/api/config")
        assert resp.status_code == 200
        assert resp.json()["api_key"] == ""

    def test_post_config_saves_key(self, client, monkeypatch):
        """POST /api/config：写 API Key 走 patch 的 set_api_key，返回 ok。"""
        saved = {}

        def fake_set(api_key):
            saved["api_key"] = api_key

        monkeypatch.setattr(config_routes, "set_api_key", fake_set)
        resp = client.post("/api/config", data={"api_key": "sk-test-123"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert saved["api_key"] == "sk-test-123"

    def test_delete_config_env_source_rejected(self, client, monkeypatch):
        """DELETE /api/config：env 来源的 key 无法从界面清除 → 400。"""
        monkeypatch.setattr(config_routes, "get_api_key_source", lambda: "env")
        resp = client.delete("/api/config")
        assert resp.status_code == 400
        assert "环境变量" in resp.json()["detail"]

    def test_delete_config_clears_key(self, client, monkeypatch):
        monkeypatch.setattr(config_routes, "get_api_key_source", lambda: "config")
        cleared = {"called": False}

        def fake_delete():
            cleared["called"] = True

        monkeypatch.setattr(config_routes, "delete_api_key", fake_delete)
        resp = client.delete("/api/config")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}
        assert cleared["called"] is True

    def test_save_watermark_toggle(self, client, monkeypatch):
        saved = {}

        def fake_set(enabled):
            saved["enabled"] = enabled

        monkeypatch.setattr(config_routes, "set_watermark_config", fake_set)
        resp = client.post("/api/config/watermark", data={"enabled": "true"})
        assert resp.status_code == 200
        assert resp.json() == {"ok": True, "enabled": True}
        assert saved["enabled"] is True

    def test_save_models_requires_text_model(self, client, monkeypatch):
        """POST /api/config/models：text 为空 → 400。"""
        resp = client.post("/api/config/models", data={})
        assert resp.status_code == 400
        assert "文本模型不能为空" in resp.json()["detail"]

    def test_save_domain_validates_suffix(self, client, monkeypatch):
        """POST /api/config/domain：非法域名后缀 → 422。"""
        monkeypatch.setattr(config_routes, "set_agnes_domain", lambda d: None)
        resp = client.post("/api/config/domain", data={"domain": "evil"})
        assert resp.status_code == 422
        assert "域名后缀" in resp.json()["detail"]

        monkeypatch.setattr(config_routes, "set_agnes_domain", lambda d: d)
        ok = client.post("/api/config/domain", data={"domain": "cn"})
        assert ok.status_code == 200
        assert ok.json()["agnes_domain"] == "cn"


# ═══════════════════════════════════════════════
# 2. workspaces 路由
# ═══════════════════════════════════════════════

class TestWorkspaceRoutes:
    def test_list_workspaces(self, client, monkeypatch):
        monkeypatch.setattr(workspace_routes, "get_workspaces", lambda: ["/tmp/ws"])
        monkeypatch.setattr(workspace_routes, "get_active_workspace", lambda: "/tmp/ws")
        resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        assert resp.json() == {"workspaces": ["/tmp/ws"], "active_workspace": "/tmp/ws"}

    def test_create_workspace_empty_path_422(self, client):
        resp = client.post("/api/workspaces", data={"path": "   "})
        assert resp.status_code == 422
        assert "不能为空" in resp.json()["detail"]

    def test_create_workspace_unsafe_path_422(self, client, monkeypatch):
        def unsafe(path):
            raise UnsafePathError("out of root")

        monkeypatch.setattr(workspace_routes, "safe_workspace_path", unsafe)
        resp = client.post("/api/workspaces", data={"path": "/etc/passwd"})
        assert resp.status_code == 422
        assert "不合法" in resp.json()["detail"]

    def test_create_workspace_success(self, client, monkeypatch, tmp_path):
        """创建成功：safe 路径落盘到 tmp_path，返回 workspace 条目。"""
        ws_dir = str(tmp_path / "ws1")
        monkeypatch.setattr(workspace_routes, "safe_workspace_path", lambda p: ws_dir)
        monkeypatch.setattr(
            workspace_routes, "add_workspace",
            lambda path, name: {"path": path, "name": name},
        )
        monkeypatch.setattr(workspace_routes, "get_active_workspace", lambda: ws_dir)

        resp = client.post("/api/workspaces", data={"path": ws_dir, "name": "测试工作区"})
        assert resp.status_code == 200
        assert resp.json()["workspace"]["name"] == "测试工作区"
        assert os.path.isdir(os.path.join(ws_dir, "uploads")), "应创建 uploads 子目录"

    def test_delete_workspace_missing_404(self, client, monkeypatch):
        monkeypatch.setattr(workspace_routes, "remove_workspace", lambda p: None)
        resp = client.request("DELETE", "/api/workspaces", data={"path": "/tmp/nope"})
        assert resp.status_code == 404
        assert "不存在" in resp.json()["detail"]

    def test_delete_workspace_success(self, client, monkeypatch):
        monkeypatch.setattr(workspace_routes, "remove_workspace", lambda p: {"path": p})
        monkeypatch.setattr(workspace_routes, "get_active_workspace", lambda: "")
        resp = client.request("DELETE", "/api/workspaces", data={"path": "/tmp/ws"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_activate_workspace_unsafe_422(self, client, monkeypatch):
        def unsafe(path):
            raise UnsafePathError("out of root")

        monkeypatch.setattr(workspace_routes, "safe_workspace_path", unsafe)
        resp = client.post("/api/workspaces/active", data={"path": "/etc"})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════
# 3. voices 路由
# ═══════════════════════════════════════════════

class TestVoiceRoutes:
    def test_voices_catalog_structure(self, client):
        """GET /api/voices：按语言分组 + compat_hint，zh 组含 XiaoxiaoNeural。"""
        resp = client.get("/api/voices")
        assert resp.status_code == 200
        data = resp.json()
        assert "languages" in data and "compat_hint" in data
        langs = {item["code"] for item in data["languages"]}
        assert "zh" in langs
        zh = next(item for item in data["languages"] if item["code"] == "zh")
        assert any(v["id"] == "zh-CN-XiaoxiaoNeural" for v in zh["voices"])
        assert data["languages"][0]["count"] == len(data["languages"][0]["voices"])

    def test_voice_compat_query(self, client):
        """GET /api/voices/compat：zh 音色对 zh 兼容、含 supported_langs。"""
        resp = client.get(
            "/api/voices/compat",
            params={"voice": "zh-CN-XiaoxiaoNeural", "target_lang": "zh"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["compatible"] is True
        assert data["voice_lang"] == "zh"
        assert data["target_lang"] == "zh"
        assert "zh" in data["supported_langs"]

    def test_voice_compat_cross_script(self, client):
        """zh 音色 + ru 目标语言 → 跨文字体系不兼容（compatible=False）。"""
        resp = client.get(
            "/api/voices/compat",
            params={"voice": "zh-CN-XiaoxiaoNeural", "target_lang": "ru"},
        )
        assert resp.status_code == 200
        assert resp.json()["compatible"] is False

    def test_voice_preview_empty_voice_400(self, client):
        """GET /api/voices/preview：voice 为空串 → 400。"""
        resp = client.get("/api/voices/preview", params={"voice": ""})
        assert resp.status_code == 400
        assert "voice" in resp.json()["detail"]

    def test_voice_preview_missing_voice_422(self, client):
        """GET /api/voices/preview：缺 voice 参数 → FastAPI 必填校验 422。"""
        resp = client.get("/api/voices/preview")
        assert resp.status_code == 422


# ═══════════════════════════════════════════════
# 4. task_creation 路由：参数校验矩阵
# ═══════════════════════════════════════════════

class TestTaskCreationValidation:
    """无 API Key / 非法参数 → 4xx；合法参数 → 200（全部写路径打桩）。"""

    def test_simple_requires_api_key(self, client, monkeypatch):
        monkeypatch.setattr(task_creation_routes, "get_api_key", lambda: "")
        resp = client.post("/api/tasks/simple", data={"prompt": "test"})
        assert resp.status_code == 400
        assert "API Key" in resp.json()["detail"]

    def test_simple_invalid_mode_422(self, client, task_env):
        resp = client.post("/api/tasks/simple", data={"prompt": "test", "mode": "warp"})
        assert resp.status_code == 422
        assert "mode 必须" in resp.json()["detail"]

    def test_simple_invalid_duration_422(self, client, task_env):
        resp = client.post("/api/tasks/simple", data={"prompt": "test", "duration": "7"})
        assert resp.status_code == 422
        assert "duration 必须" in resp.json()["detail"]

    def test_simple_prompt_too_long_422(self, client, task_env):
        resp = client.post("/api/tasks/simple", data={"prompt": "x" * 5001})
        assert resp.status_code == 422
        assert "5000" in resp.json()["detail"]

    def test_simple_valid_creates_task(self, client, task_env):
        """合法请求 → 200 + task_id，且确实收集到后台任务 coro。"""
        resp = client.post(
            "/api/tasks/simple",
            data={"prompt": "一只猫在花园里", "mode": "t2v", "duration": "5"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and len(body["task_id"]) == 12
        assert len(task_env) == 1, "应启动一个后台任务"

    def test_creative_invalid_scene_count_422(self, client, task_env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险", "scene_count": "31", "duration_source": "manual"},
        )
        assert resp.status_code == 422
        assert "scene_count 范围" in resp.json()["detail"]

    def test_creative_invalid_duration_source_422(self, client, task_env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险", "duration_source": "auto"},
        )
        assert resp.status_code == 422
        assert "duration_source" in resp.json()["detail"]

    def test_creative_bad_scene_durations_json_422(self, client, task_env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险", "scene_durations_json": "not-json"},
        )
        assert resp.status_code == 422
        assert "JSON 数组" in resp.json()["detail"]

    def test_creative_scene_duration_out_of_range_422(self, client, task_env):
        """时长数值越界（1 秒 < 2 下限）→ 422。"""
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险", "scene_durations_json": "[1,5,5]"},
        )
        assert resp.status_code == 422
        assert "2-30" in resp.json()["detail"]

    def test_creative_valid_creates_task(self, client, task_env):
        resp = client.post(
            "/api/tasks/creative",
            data={"idea": "太空探险故事", "scene_count": "3", "scene_durations_json": "[5,8,5]"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert len(task_env) == 1

    def test_manuscript_empty_text_400(self, client, task_env):
        resp = client.post("/api/tasks/manuscript", data={"manuscript_text": "  "})
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_manuscript_too_long_422(self, client, task_env):
        resp = client.post("/api/tasks/manuscript", data={"manuscript_text": "长" * 50001})
        assert resp.status_code == 422
        assert "50000" in resp.json()["detail"]

    def test_manuscript_valid_creates_task(self, client, task_env):
        resp = client.post(
            "/api/tasks/manuscript",
            data={"manuscript_text": "这是一段测试稿件。", "audio_enabled": "false"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_poetry_empty_poem_400(self, client, task_env):
        resp = client.post("/api/tasks/poetry", data={"poem_text": "   "})
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_poetry_invalid_duration_422(self, client, task_env):
        resp = client.post("/api/tasks/poetry", data={"poem_text": "床前明月光", "video_duration": "400"})
        assert resp.status_code == 422
        assert "5-300" in resp.json()["detail"]

    def test_poetry_bad_user_scene_prompts_json_422(self, client, task_env):
        resp = client.post(
            "/api/tasks/poetry",
            data={"poem_text": "床前明月光", "user_scene_prompts_json": "{oops}"},
        )
        assert resp.status_code == 422
        assert "JSON 数组" in resp.json()["detail"]

    def test_poetry_valid_creates_task(self, client, task_env):
        resp = client.post(
            "/api/tasks/poetry",
            data={"poem_text": "床前明月光，疑是地上霜。", "audio_enabled": "false"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_anchor_empty_script_400(self, client, task_env):
        resp = client.post("/api/tasks/anchor", data={"script_text": "   "})
        assert resp.status_code == 400
        assert "不能为空" in resp.json()["detail"]

    def test_anchor_valid_creates_task(self, client, task_env):
        resp = client.post(
            "/api/tasks/anchor",
            data={"script_text": "大家好，欢迎收看本期节目。", "audio_enabled": "false"},
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_legacy_tasks_endpoint_maps_to_creative(self, client, task_env):
        """旧 POST /api/tasks → 映射 creative，正常返回 task_id。"""
        resp = client.post("/api/tasks", data={"idea": "兼容旧端点测试"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


# ═══════════════════════════════════════════════
# 5. 无状态工具路由
# ═══════════════════════════════════════════════

class TestUtilityRoutes:
    def test_poetry_scene_prompt_endpoint(self, client):
        """GET /api/poetry-scene-prompt：纯字符串构造，返回 system/user prompt。"""
        resp = client.get(
            "/api/poetry-scene-prompt",
            params={"poem": "床前明月光", "scene_count": "2", "scene_durations": "[5,5]", "style": "水墨"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert set(data) == {"system_prompt", "user_prompt"}
        assert "<poem>" in data["user_prompt"]
        assert "床前明月光" in data["user_prompt"]
        assert "水墨" in data["user_prompt"]

    def test_poetry_scene_prompt_bad_durations_ignored(self, client):
        """scene_durations 非法 JSON → 忽略（空列表），仍返回提示词。"""
        resp = client.get(
            "/api/poetry-scene-prompt",
            params={"poem": "床前明月光", "scene_durations": "not-json"},
        )
        assert resp.status_code == 200
        assert set(resp.json()) == {"system_prompt", "user_prompt"}
