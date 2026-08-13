// 统一 API 封装：与后端 21 个端点一一对应
// 任务提交类用 FormData（含文件上传），其余用 JSON

async function request<T = any>(url: string, options?: RequestInit): Promise<T> {
  const r = await fetch(url, options)
  return r.json()
}

// ── 配置 ──
export function getConfig() {
  return request('/api/config')
}
export function saveApiKey(apiKey: string) {
  const form = new FormData()
  form.append('api_key', apiKey)
  return fetch('/api/config', { method: 'POST', body: form })
}
export function clearApiKey() {
  return fetch('/api/config', { method: 'DELETE' })
}
export function saveDomain(domain: string) {
  const form = new FormData()
  form.append('domain', domain)
  return fetch('/api/config/domain', { method: 'POST', body: form })
}
export function saveModels(models: { text?: string; image?: string; video?: string }) {
  const form = new FormData()
  if (models.text) form.append('text', models.text)
  if (models.image) form.append('image', models.image)
  if (models.video) form.append('video', models.video)
  return fetch('/api/config/models', { method: 'POST', body: form })
}
export function setWatermark(enabled: boolean) {
  const form = new FormData()
  form.append('enabled', String(enabled))
  return fetch('/api/config/watermark', { method: 'POST', body: form })
}

// ── 模型 ──
export function getModels(refresh = false) {
  return request('/api/models' + (refresh ? '?refresh=1' : ''))
}

// ── 音色 ──
export function getVoices() {
  return request('/api/voices')
}

// ── 工作区 ──
export function getWorkspaces() {
  return request('/api/workspaces')
}
export function activateWorkspace(path: string) {
  const form = new FormData()
  form.append('path', path)
  return fetch('/api/workspaces/active', { method: 'POST', body: form })
}
export function addWorkspace(path: string, name: string) {
  const form = new FormData()
  form.append('path', path)
  form.append('name', name)
  return fetch('/api/workspaces', { method: 'POST', body: form })
}
export function removeWorkspace(path: string) {
  const form = new FormData()
  form.append('path', path)
  return fetch('/api/workspaces', { method: 'DELETE', body: form })
}
export function pickDirectory() {
  return request('/api/workspaces/pick-directory')
}

// ── 任务列表与详情 ──
export function getTasks() {
  return request('/api/tasks')
}
export function getTask(taskId: string) {
  return request('/api/tasks/' + taskId)
}
export function resumeTask(taskId: string) {
  return fetch('/api/tasks/' + taskId + '/resume', { method: 'POST' }).then((r) => r.json())
}
export function stopTask(taskId: string) {
  return fetch('/api/tasks/' + taskId + '/stop', { method: 'POST' }).then((r) => r.json())
}

// ── 产物 ──
export function getArtifacts(taskId: string) {
  return request('/api/tasks/' + taskId + '/artifacts')
}
export function getArtifactFileUrl(taskId: string, artifactId: string) {
  return '/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId) + '/file'
}
export function getArtifactCascadePreview(taskId: string, artifactId: string) {
  return request('/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId) + '/cascade-preview')
}
export function deleteArtifact(taskId: string, artifactId: string) {
  return fetch('/api/tasks/' + taskId + '/artifacts/' + encodeURIComponent(artifactId), { method: 'DELETE' }).then(
    (r) => r.json(),
  )
}

// ── 诗词场景提示词 ──
export function getPoetryScenePrompt(params: Record<string, string>) {
  const qs = new URLSearchParams(params)
  return request('/api/poetry-scene-prompt?' + qs.toString())
}

// ── 任务提交（FormData 多文件上传）──
export function submitSimple(form: FormData) {
  return fetch('/api/tasks/simple', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitCreative(form: FormData) {
  return fetch('/api/tasks/creative', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitManuscript(form: FormData) {
  return fetch('/api/tasks/manuscript', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitAnchor(form: FormData) {
  return fetch('/api/tasks/anchor', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitPoetry(form: FormData) {
  return fetch('/api/tasks/poetry', { method: 'POST', body: form }).then((r) => r.json())
}
export function submitImage(form: FormData) {
  return fetch('/api/image/generate', { method: 'POST', body: form }).then((r) => r.json())
}
