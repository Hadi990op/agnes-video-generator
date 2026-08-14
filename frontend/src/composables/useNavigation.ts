import { appState } from '@/store'

// 顶层视图导航 + URL hash 同步（无 vue-router，零后端改动）
// hash 规则：'#/progress/<taskId>' | '#/list' | '#/create'

export function useNavigation() {
  function goProgress(taskId: string, origin: 'create' | 'list' = 'create') {
    appState.view = 'progress'
    appState.progressTaskId = taskId
    appState.progressOrigin = origin
    appState.currentTaskId = taskId
    location.hash = '#/progress/' + encodeURIComponent(taskId)
  }

  function goBack() {
    const origin = appState.progressOrigin === 'list' ? 'list' : 'create'
    appState.view = origin
    appState.progressTaskId = null
    location.hash = origin === 'list' ? '#/list' : '#/create'
  }

  function parseHash(): { view: 'create' | 'list' | 'progress'; taskId?: string } {
    const h = location.hash || ''
    const m = h.match(/^#\/progress\/(.+)$/)
    if (m) return { view: 'progress', taskId: decodeURIComponent(m[1]) }
    if (h.startsWith('#/list')) return { view: 'list' }
    return { view: 'create' }
  }

  return { goProgress, goBack, parseHash }
}
