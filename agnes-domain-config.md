# Agnes 域名配置（v6.0）— 变更概述

## 变更内容

在页面顶部新增第四项配置——**Agnes 域名配置**，允许用户在 `.com` 和 `.cn` 两个域名后缀间切换。

### 默认行为
- 中文界面下推荐 `.cn`（中国大陆访问更流畅）
- 其他语言默认 `.com`

## 修改的文件

| 文件 | 变更 |
|------|------|
| `core/config.py` | 新增 `get_agnes_domain()`、`set_agnes_domain()`、`get_agnes_base_url()`、`get_agnes_api_root()` 函数及域名字典 |
| `core/api/agnes_chat.py` | 将硬编码 `BASE_URL` 改为运行时调用 `get_agnes_base_url()` |
| `core/api/agnes_image.py` | 同上 |
| `core/api/agnes_video.py` | 将 `BASE_URL` / `API_ROOT` 改为运行时调用 |
| `core/api/agnes_models.py` | 将 `MODELS_ENDPOINT` 改为动态构造 |
| `server.py` | `GET /api/config` 返回 `agnes_domain`/`agnes_domains`；新增 `POST /api/config/domain` 端点 |
| `static/index.html` | 新增域名配置 UI 面板（折叠/展开），13 种语言的 i18n 翻译，JS 交互逻辑 |

## 配置存储

写入 `.agnes_config/config.json`，key 为 `"agnes_domain"`，值为 `"com"` 或 `"cn"`。

## UI 说明

- 位于"模型选择"和"工作目录"之间
- 样式与其他三个配置面板完全一致（glass-card、折叠/展开、紧凑栏）
- 两个单选按钮分别对应 `.com` 和 `.cn`
- 下方有一段说明文本：在中国推荐使用 `.cn` 域名以获得更稳定流畅的访问体验
- 保存后状态持久化，页面刷新后仍保持
