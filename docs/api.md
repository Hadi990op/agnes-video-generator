# 📋 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve Web UI |
| GET | `/api/config` | Get API key (masked) |
| POST | `/api/config` | Save API key |
| DELETE | `/api/config` | Delete API key |
| GET | `/api/voices` | List available TTS voices |
| POST | `/api/image/generate` | Image generation |
| GET | `/api/image/{task_id}` | Query image task status |
| POST | `/api/tasks/simple` | Create simple video task |
| POST | `/api/tasks/creative` | Create creative video task |
| POST | `/api/tasks/manuscript` | Create manuscript video task |
| POST | `/api/tasks/anchor` | Create digital anchor task |
| POST | `/api/tasks` | Generic task creation (backward-compatible) |
| GET | `/api/tasks` | List all tasks (with type badges) |
| GET | `/api/tasks/{id}` | Get task details |
| POST | `/api/tasks/{id}/resume` | Resume an interrupted task |
| POST | `/api/tasks/{id}/stop` | Stop a running task |
| GET | `/api/video/{id}` | Download/stream final video |
| WS | `/ws/{id}` | WebSocket real-time progress |
