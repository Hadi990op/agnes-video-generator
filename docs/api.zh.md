# 📋 API 接口

**[🌐 官网](https://video.lichuanyang.top)** | **[📚 API 文档](https://video.lichuanyang.top/api-docs)** | **[📖 调用指南](https://video.lichuanyang.top/guides/api-call)**

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Web UI 页面 |
| GET | `/api/config` | 获取 API Key（脱敏） |
| POST | `/api/config` | 保存 API Key |
| DELETE | `/api/config` | 删除 API Key |
| GET | `/api/voices` | 列出可用 TTS 语音角色 |
| POST | `/api/image/generate` | 图片生成 |
| GET | `/api/image/{task_id}` | 查询图片任务状态 |
| POST | `/api/tasks/simple` | 创建简单视频任务 |
| POST | `/api/tasks/creative` | 创建创意长视频任务 |
| POST | `/api/tasks/manuscript` | 创建稿件长视频任务 |
| POST | `/api/tasks/anchor` | 创建数字人口播任务 |
| POST | `/api/tasks` | 通用创建任务入口（兼容旧版） |
| GET | `/api/tasks` | 列出所有任务（含类型标识） |
| GET | `/api/tasks/{id}` | 查询任务详情 |
| POST | `/api/tasks/{id}/resume` | 续传中断任务 |
| POST | `/api/tasks/{id}/stop` | 停止运行中的任务 |
| GET | `/api/video/{id}` | 下载/播放最终视频 |

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
