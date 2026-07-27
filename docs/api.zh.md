# 📋 API 接口

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
| WS | `/ws/{id}` | WebSocket 实时进度推送 |
