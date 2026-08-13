# 前端（Agnes Video Generator）

本目录是 Agnes Video Generator 的 **Vue 3 + Vite + TypeScript** 前端源码。

## 架构说明

- 前端源码位于 `frontend/`，构建产物输出到项目根目录的 `static/`（`vite build` 的 `outDir` 指向 `../static`）。
- 后端 `server.py` 固定从 `static/` 伺服前端：`/` 返回 `static/index.html`，`/static/*` 伺服静态资源。
- **构建产物（`static/index.html` + `static/assets/*`）提交进 git 仓库**，因此三种部署方式（`start.sh` 一键启动 / Docker / npm 包）对终端用户**零 Node 依赖、零改动**。

## 目录结构

```
frontend/
├── index.html              # Vite 入口 HTML（含主题防闪烁脚本）
├── vite.config.ts          # outDir=../static、base=/static/、emptyOutDir=false
├── tailwind.config.js      # Tailwind 配置（自定义 token 类在 style.css 手动定义）
├── postcss.config.js
├── package.json            # 前端依赖（独立于根 package.json）
└── src/
    ├── main.ts             # 应用入口（语言/主题/GA 初始化 + 挂载）
    ├── App.vue             # 根组件：双栏布局 + 顶部导航 + 主 Tab
    ├── style.css           # 全局样式（原 index.html 内联 CSS + Tailwind 指令）
    ├── types.ts            # 与后端 models 对齐的类型定义
    ├── steps.ts            # 6 任务类型的步骤定义 + 步骤状态映射
    ├── store.ts            # 模块级 reactive 全局状态
    ├── i18n/
    │   ├── index.ts        # t()/switchLang/escapeHtml + 语言列表
    │   └── translations.ts # 22 语言文案（由旧 index.html T 对象迁移，勿手工改）
    ├── api/
    │   └── index.ts        # 21 个 API 端点统一封装
    ├── composables/
    │   ├── useTheme.ts     # 主题切换（system/light/dark）
    │   ├── useGa.ts        # GA 埋点 + 异常上报
    │   ├── useToast.ts     # Toast 提示
    │   ├── useProgress.ts  # 任务进度轮询 + 步骤状态 + 结果展示
    │   ├── useVoice.ts     # 音色选择器（分组/搜索/试听/兼容校验）
    │   ├── useConfig.ts    # API Key/模型/域名/水印/工作区
    │   ├── useTasks.ts     # 任务列表/详情/续传/停止
    │   └── useArtifacts.ts # 产物管理（列表/预览/删除）
    └── components/
        ├── ConfigPanel.vue        # 配置面板（4 个折叠面板）
        ├── CreatePanel.vue        # 新建任务（任务类型 Tab 切换）
        ├── TaskListPanel.vue      # 任务列表
        ├── ProgressPanel.vue      # 进度 + 步骤 + 产物 + 结果
        ├── VoicePickerModal.vue   # 音色选择弹窗
        ├── Toast.vue
        ├── shared/
        │   ├── VoiceSelector.vue  # 音色选择 chip
        │   ├── WatermarkToggle.vue # 水印开关
        │   └── SubtitleConfig.vue # 音频+字幕配置（创意/稿件/数字人/诗词复用）
        └── forms/
            ├── SimpleForm.vue     # 简单视频（t2v/i2v/keyframes）+ 简单图片
            ├── CreativeForm.vue   # 创意长视频
            ├── ManuscriptForm.vue # 稿件长视频
            ├── AnchorForm.vue     # 数字人口播
            └── PoetryForm.vue     # 诗词视频
```

## 开发流程

### 1. 安装依赖

```bash
cd frontend
npm install
```

### 2. 本地开发（热更新）

```bash
npm run dev
# 访问 http://localhost:5173
# 开发模式会通过 vite proxy 转发 /api 到后端（需后端已在 8765 运行）
```

> 注意：开发模式需要后端 `python server.py` 已在 8765 端口运行，API 请求会转发到后端。

### 3. 构建（生成 static/ 产物）

```bash
npm run build
```

构建产物输出到 `../static/`：
- `static/index.html`（覆盖旧的单文件）
- `static/assets/index-*.js` / `index-*.css`（hash 命名）

### 4. 提交产物

**关键**：改动 `frontend/src/` 源码后，必须重新 `npm run build` 并**提交 `static/` 产物**。否则三种部署方式会使用过期的前端。

CI（`.github/workflows/test.yml` 的 `frontend-build` job）会在每次 PR 时校验「`frontend/` 源码 build 后与提交的 `static/` 产物一致」，防止源码与产物脱节。

## 技术要点

### Tailwind 与自定义 token

- 自定义颜色类（`text-ink`/`bg-paper`/`text-accent`/`border-rule` 等）在 `style.css` 中**手动定义**（基于 `--color-*` CSS 变量），**不走** Tailwind 生成。
- Tailwind 仅用于布局类（flex/grid/spacing/rounded 等标准 utility）。
- `tailwind.config.js` 中**不定义**自定义 colors，避免与 style.css 手动定义冲突。

### i18n

- 22 语言文案集中在 `src/i18n/translations.ts`（由旧 index.html 的 T 对象迁移）。
- 组件通过 `t(key)` 取文案，语言切换通过 `switchLang()` 触发全局响应式更新。
- 文案 key 与旧代码完全一致，迁移零丢失。

### 音色选择器

- 音色目录通过 `/api/voices` 加载，按语言分组。
- 选择时做跨语言兼容性校验（`compat_hint`），不兼容时弹确认框。

### 进度轮询

- 提交任务后 `startPolling()` 每 30s 轮询 `/api/tasks/{id}`。
- 步骤状态（done/running/pending）根据后端 `step_*` 字段映射渲染。
- 产物（中间结果）通过 `/api/tasks/{id}/artifacts` 加载，按步骤分组展示。

## 兼容性约束（勿改）

- `/` 与 `/static/*` 路由语义不变（后端 `server.py`）。
- 21 个 API 端点、请求体字段与旧代码一一对应。
- `static/favicon.ico`、`static/icon.png`、`static/generated/` 为后端依赖资源，`vite build` 的 `emptyOutDir=false` 确保不清空它们。
