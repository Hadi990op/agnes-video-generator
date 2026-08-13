import { reactive, ref, computed } from 'vue'
import { appState } from '@/store'
import * as api from '@/api'
import { t } from '@/i18n'
import { useToast } from './useToast'
import { useGa } from './useGa'

const { showToast } = useToast()
const { trackEvent } = useGa()

// ── API Key ──
const apiKeyStatus = ref<'none' | 'configured' | 'env'>('none')
// 多 Key（v5.0 优化）：当前 Key 数 + 采集来源 + 去重后的 Key 列表（含来源标记）
const keyCount = ref(0)
const keySource = ref('')
const keyList = ref<{ key: string; source: string }[]>([])

function isApiKeyConfigured() {
  return apiKeyStatus.value !== 'none'
}

async function saveApiKey(key: string) {
  const r = await api.saveApiKey(key)
  if (r.ok) {
    trackEvent('config_action', { action: 'save_api_key' })
    apiKeyStatus.value = 'configured'
    await loadKeyInfo()
  }
}

async function loadKeyInfo() {
  try {
    const d = await api.getConfigKeys()
    keyCount.value = d.key_count || 0
    keySource.value = d.source || ''
    keyList.value = d.keys || []
    // 同步 Key 状态：source 以 'env' 开头（env:1 / mixed:...）→ env；有 Key → configured
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
  } catch (e) {
    console.error('load /api/config/keys failed:', e)
  }
}

async function removeKey(key: string) {
  if (!confirm(t('removeKeyConfirm'))) return false
  const r = await api.removeConfigKey(key)
  if (r.ok) {
    trackEvent('config_action', { action: 'remove_api_key' })
    if (r.still_active) {
      showToast(t('keyStillActive') + ': ' + r.removed, 3500)
    } else {
      showToast(t('removedKey') + ': ' + r.removed, 3000)
    }
    keyCount.value = r.key_count || 0
    keySource.value = r.source || ''
    keyList.value = (await api.getConfigKeys()).keys || []
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
    return true
  }
  alert(r.detail || t('failRemoveKey'))
  return false
}

function maskKey(key: string): string {
  if (key.length <= 12) return key
  return key.slice(0, 6) + '••••' + key.slice(-4)
}

async function saveMultiKeys(keysText: string) {
  const parts = keysText
    .split(/[\n,，;；\s]+/)
    .map((s) => s.trim())
    .filter(Boolean)
  if (parts.length === 0) return false
  // 已有 Key 时自动切换「追加」模式：新 Key 与现有 Key 合并，无需重输旧 Key
  const append = keyCount.value > 0
  const r = await api.saveConfigKeys(parts, append)
  if (r.ok) {
    trackEvent('config_action', { action: append ? 'add_api_key' : 'save_multi_api_keys', count: parts.length })
    keyCount.value = r.key_count || 0
    keySource.value = r.source || ''
    // source 以 'env' 开头（env:1 / mixed:...）→ env 优先；否则按 config 计
    if (keyCount.value > 0) {
      apiKeyStatus.value = keySource.value.startsWith('env') ? 'env' : 'configured'
    } else {
      apiKeyStatus.value = 'none'
    }
    return true
  }
  return false
}

async function clearApiKey() {
  if (apiKeyStatus.value === 'env') {
    alert(t('clearEnvHint'))
    return
  }
  if (!confirm(t('clearConfirm'))) return
  const r = await api.clearApiKey()
  if (r.ok) {
    trackEvent('config_action', { action: 'clear_api_key' })
    apiKeyStatus.value = 'none'
  } else {
    const d = await r.json().catch(() => ({}))
    alert(d.detail || 'Failed to clear')
  }
}

// ── 模型 ──
const modelSyncStatus = ref<'idle' | 'syncing' | 'ok' | 'error'>('idle')
const modelSaveStatus = ref<'idle' | 'ok' | 'error'>('idle')
const modelErrorMsg = ref('')

// 2.5-flash 已正式上线（无内测标记）；pro 系列为付费模型
function isBetaModel(m: string): boolean {
  // 保留通用性：仍匹配任何带 "beta" 字样的模型（未来若有新 beta 模型）
  return typeof m === 'string' && /beta/i.test(m)
}

function isPaidModel(m: string): boolean {
  return typeof m === 'string' && /agnes-2\.5-pro|agnes-2\.5-pro-alpha/.test(m)
}

const betaHintVisible = computed(() => {
  const val = (appState.models.text || '').replace(t('modelBetaTag'), '')
  return isBetaModel(val)
})

async function loadModels() {
  try {
    const r = await fetch('/api/models')
    if (r.ok) {
      const d = await r.json()
      if (d.models) appState.modelListCache = d.models
    }
  } catch (e) {
    console.error('load /api/models failed:', e)
  }
  try {
    const cd = await api.getConfig()
    const sel = cd.models || {}
    appState.models = { text: sel.text || '', image: sel.image || '', video: sel.video || '' }
  } catch (e) {
    console.error('load model config failed:', e)
  }
}

async function syncModels() {
  modelSyncStatus.value = 'syncing'
  try {
    const r = await fetch('/api/models?refresh=1')
    if (r.ok) {
      const d = await r.json()
      if (d.models) appState.modelListCache = d.models
      modelSyncStatus.value = 'ok'
      setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
    } else {
      modelSyncStatus.value = 'error'
      setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
    }
  } catch (e) {
    modelSyncStatus.value = 'error'
    setTimeout(() => (modelSyncStatus.value = 'idle'), 1500)
  }
}

async function saveModels() {
  if (!appState.models.text) {
    modelSaveStatus.value = 'error'
    modelErrorMsg.value = t('modelTextRequired')
    return
  }
  try {
    const r = await api.saveModels(appState.models)
    if (r.ok) {
      trackEvent('config_action', { action: 'save_models', text_model: appState.models.text })
      modelSaveStatus.value = 'ok'
      setTimeout(() => (modelSaveStatus.value = 'idle'), 2000)
    } else {
      const d = await r.json().catch(() => ({}))
      modelErrorMsg.value = d.detail || t('modelSaveFailed')
      modelSaveStatus.value = 'error'
    }
  } catch (e) {
    modelErrorMsg.value = t('networkError')
    modelSaveStatus.value = 'error'
  }
}

// ── 域名 ──
const domainSaveStatus = ref<'idle' | 'ok' | 'error'>('idle')
const domainErrorMsg = ref('')

async function saveDomain() {
  const domain = appState.agnesDomain
  try {
    const r = await api.saveDomain(domain)
    if (r.ok) {
      trackEvent('config_action', { action: 'save_domain', domain })
      domainSaveStatus.value = 'ok'
      setTimeout(() => (domainSaveStatus.value = 'idle'), 2000)
    } else {
      const d = await r.json().catch(() => ({}))
      domainErrorMsg.value = d.detail || t('domainSaveFailed')
      domainSaveStatus.value = 'error'
    }
  } catch (e) {
    domainErrorMsg.value = t('networkError')
    domainSaveStatus.value = 'error'
  }
}

// ── 水印 ──
async function toggleWatermark(enabled: boolean) {
  const r = await api.setWatermark(enabled)
  if (r.ok) {
    trackEvent('config_action', { action: 'toggle_watermark', enabled: enabled ? 'on' : 'off' })
    appState.watermarkEnabled = enabled
    showToast(enabled ? t('watermarkEnabled') : t('watermarkDisabled'))
  }
}

// ── 工作区 ──
const isRegression = computed(() => appState.workingDirSource === 'regression')

function wsDisplayName(ws: any): string {
  if (ws && ws.is_default) return t('workspaceDefault')
  return (ws && (ws.name || ws.path)) || ''
}

async function renderWorkspaces() {
  try {
    const d = await api.getWorkspaces()
    const cfg = await api.getConfig()
    appState.workspaces = d.workspaces || []
    appState.activeWorkspace = d.active_workspace || ''
    appState.workingDirSource = cfg.working_dir_source || 'config'
  } catch (e) {
    console.error('renderWorkspaces error:', e)
  }
}

async function activateWorkspace(path: string) {
  const r = await api.activateWorkspace(path)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    alert(d.detail || 'Failed')
  }
}

async function removeWorkspaceEntry(path: string) {
  if (!confirm(t('workspaceRemoveConfirm'))) return
  const r = await api.removeWorkspace(path)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    alert(d.detail || 'Failed')
  }
}

async function browseDirectory(): Promise<string | null> {
  try {
    const d = await api.pickDirectory()
    if (d.ok && d.path) return d.path
  } catch (e) {
    alert('Network error')
  }
  return null
}

async function addWorkspace(path: string, name: string) {
  if (!path) return
  const r = await api.addWorkspace(path, name)
  if (r.ok) {
    await renderWorkspaces()
  } else {
    const d = await r.json().catch(() => ({}))
    alert(d.detail || 'Failed')
  }
}

export function useConfig() {
  return {
    apiKeyStatus,
    keyCount,
    keySource,
    keyList,
    maskKey,
    isApiKeyConfigured,
    saveApiKey,
    saveMultiKeys,
    loadKeyInfo,
    removeKey,
    clearApiKey,
    modelSyncStatus,
    modelSaveStatus,
    modelErrorMsg,
    betaHintVisible,
    isBetaModel,
    isPaidModel,
    loadModels,
    syncModels,
    saveModels,
    domainSaveStatus,
    domainErrorMsg,
    saveDomain,
    toggleWatermark,
    isRegression,
    wsDisplayName,
    renderWorkspaces,
    activateWorkspace,
    removeWorkspaceEntry,
    browseDirectory,
    addWorkspace,
  }
}
