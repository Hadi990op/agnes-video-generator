# 📋 API Endpoints

> Frontend polls task state via `GET /api/tasks/{id}` — there is **no WebSocket** endpoint.

## 配置与工作区

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Web UI |
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| DELETE | `/api/config` | Clear API key |
| GET | `/api/models` | List available Agnes models (text/image/video groups, cached) |
| POST | `/api/config/models` | Save selected models |
| POST | `/api/config/watermark` | Save watermark toggle |
| POST | `/api/config/domain` | Set Agnes API domain suffix (`com`/`cn`) |
| GET | `/api/workspaces` | List workspaces |
| POST | `/api/workspaces` | Create workspace |
| DELETE | `/api/workspaces` | Delete workspace |
| POST | `/api/workspaces/active` | Activate workspace |
| GET | `/api/workspaces/pick-directory` | Native directory picker |

## 音色 (TTS Voices)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/voices` | List available TTS voices (grouped by 13 languages) |
| GET | `/api/voices/preview` | Voice preview (generated/cached sample) |
| GET | `/api/voices/compat` | Voice × language compatibility check |

## 图片 (Image)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/image/generate` | Generate simple image (t2i / i2i) |
| GET | `/api/image/{task_id}` | Download/preview generated image |

## 任务创建 (Task Creation)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| POST | `/api/tasks/poetry` | Create poetry video task |
| POST | `/api/tasks/anchor` | Create digital-anchor task |
| POST | `/api/tasks` | Legacy task creation (mapped to creative) |
| GET | `/api/poetry-scene-prompt` | Pre-generate poetry scene prompts |

## 任务查询与控制 (Task Query & Control)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks` | List all tasks (with `task_type`) |
| GET | `/api/tasks/{task_id}` | Query task detail (polling progress) |
| POST | `/api/tasks/{task_id}/resume` | Resume interrupted task |
| POST | `/api/tasks/{task_id}/stop` | Stop running task |
| POST | `/api/tasks/sweep` | Sweep zombie task directories from disk |
| GET | `/api/concurrency` | Concurrency semaphore utilization |
| GET | `/api/video/{task_id}` | Download/stream final video |

## 中间产物 (Artifacts)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tasks/{task_id}/artifacts` | List task artifacts |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/file` | Download artifact file |
| GET | `/api/tasks/{task_id}/artifacts/{artifact_id}/cascade-preview` | Preview cascade-deletion impact |
| DELETE | `/api/tasks/{task_id}/artifacts/{artifact_id}` | Delete artifact (with cascade) |

## 运维 (Ops)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/cleanup-regression` | Clean up regression-test artifacts |

## 快速示例（curl）

```bash
# 1. 保存 API Key（免费获取：https://platform.agnes-ai.com）
curl -X POST http://localhost:8765/api/config -F "api_key=sk-你的Key"

# 2. 创建简单视频任务
curl -X POST http://localhost:8765/api/tasks/simple \
  -F "prompt=一只橘猫趴在雨后窗台上打盹，4K 写实" \
  -F "mode=t2v" \
  -F "duration=5" \
  -F "resolution=768x1152"

# 3. 轮询任务状态，直到 status=completed
curl http://localhost:8765/api/tasks/<task_id>

# 4. 下载最终视频
curl -o output.mp4 http://localhost:8765/api/video/<task_id>
```
