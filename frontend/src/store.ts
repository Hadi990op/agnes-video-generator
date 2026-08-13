import { reactive } from 'vue'
import type { TaskType, VoiceCatalog, Workspace } from './types'

// 全局应用状态（模块级 reactive，跨组件共享）
export const appState = reactive({
  // 任务类型 tab
  currentTaskType: 'creative' as TaskType | string,
  // 运行中任务
  isTaskRunning: false,
  currentTaskId: null as string | null,
  currentDirName: null as string | null,
  // 当前产物任务
  currentArtifactsTaskId: null as string | null,
  // 配置
  apiKeySource: '' as string, // 'env' | 'config' | ''
  workspaces: [] as Workspace[],
  activeWorkspace: '' as string,
  workingDirSource: 'config' as string,
  watermarkEnabled: false,
  agnesDomain: 'com' as string,
  models: { text: '', image: '', video: '' },
  modelListCache: { text: [] as string[], image: [] as string[], video: [] as string[] },
  // 音色目录
  voiceCatalog: null as VoiceCatalog | null,
  voiceIndex: {} as Record<string, any>,
})

// 折叠偏好
export function getCollapsePrefs(): Record<string, boolean> {
  try {
    return JSON.parse(localStorage.getItem('wb_config_collapsed') || '{}')
  } catch {
    return {}
  }
}

export function setCollapsePref(section: string, val: boolean) {
  const prefs = getCollapsePrefs()
  prefs[section] = val
  try {
    localStorage.setItem('wb_config_collapsed', JSON.stringify(prefs))
  } catch {
    /* ignore */
  }
}
