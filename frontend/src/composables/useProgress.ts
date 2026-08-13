import { ref, computed } from 'vue'
import { appState } from '@/store'
import { getStepsForType, isStepDoneInState } from '@/steps'
import * as api from '@/api'
import { t } from '@/i18n'
import { useGa } from './useGa'
import { useArtifacts } from './useArtifacts'
import type { TaskState, StepDef } from '@/types'

const POLL_INTERVAL = 30000

const { trackTaskResultOnce } = useGa()

// 产物刷新（模块级单例，与 ProgressPanel 共享状态）
const { loadArtifacts, scheduleArtifactRefresh } = useArtifacts()

// 进度展示状态
const progressVisible = ref(false)
const progressPct = ref(0)
const progressMessage = ref('')
const resultVideoVisible = ref(false)
const resultVideoSrc = ref('')
const steps = ref<StepDef[]>([])
const stepStates = ref<Record<string, 'done' | 'running' | 'pending'>>({})
const failedMessage = ref('')
const taskFailed = ref(false)

let pollTimer: ReturnType<typeof setInterval> | null = null

function resetSteps(taskType: string) {
  steps.value = getStepsForType(taskType)
  const st: Record<string, 'done' | 'running' | 'pending'> = {}
  steps.value.forEach((s) => (st[s.key] = 'pending'))
  stepStates.value = st
}

function markStep(stepKey: string, status: 'done' | 'running' | 'pending') {
  stepStates.value[stepKey] = status
}

function markCompletedStepsFromState(state: TaskState) {
  const taskType = state.task_type || appState.currentTaskType || 'creative'
  steps.value.forEach((s) => {
    if (isStepDoneInState(state, s.key, taskType)) {
      markStep(s.key, 'done')
    }
  })
}

function setProgressMessageHtml(html: string) {
  progressMessage.value = html
}

const currentRunningStep = computed(() => {
  return steps.value.find((s) => stepStates.value[s.key] === 'running')
})

async function showProgress(taskId: string, dirName?: string | null) {
  progressVisible.value = true
  taskFailed.value = false
  resultVideoVisible.value = false
  progressPct.value = 0

  let state: TaskState | null = null
  try {
    state = await api.getTask(taskId)
    if (state && state.task_type) appState.currentTaskType = state.task_type
  } catch {
    /* ignore */
  }

  resetSteps(appState.currentTaskType)

  // 标记已完成步骤
  if (state) {
    markCompletedStepsFromState(state)
    const step = (state.current_step || '').replace(/^step_/, '')
    const status = state.current_status || ''
    if (step && status === 'running') {
      markStep(step, 'running')
    }
  }

  const dirInfo = dirName ? `<br><span class="text-muted text-xs">${t('dir')}: <span class="font-mono">${dirName}</span></span>` : ''
  progressMessage.value = `<span class="text-accent animate-pulse">${t('taskStarting')}</span><br><span class="text-muted">${t('task_')}: ${taskId}</span>${dirInfo}`

  // 加载已有中间产物（任务运行中也可查看）
  appState.currentArtifactsTaskId = taskId
  loadArtifacts()
}

async function pollTaskProgress(taskId: string) {
  if (!appState.isTaskRunning || !taskId) return
  try {
    const state = await api.getTask(taskId)

    progressPct.value = Math.round((state.current_progress || 0) * 100)
    if (state.current_message) {
      progressMessage.value = state.current_message
    }

    markCompletedStepsFromState(state)

    const step = (state.current_step || '').replace(/^step_/, '')
    const status = state.current_status || ''
    if (step && status === 'running') {
      markStep(step, 'running')
    }

    // 步骤 running 或完成时刷新产物列表（running 期间产物逐步生成）
    if (step) {
      scheduleArtifactRefresh()
    }

    if (state.status === 'completed') {
      trackTaskResultOnce('task_completed', taskId, { task_type: state.task_type || appState.currentTaskType })
      showResult(state.final_video_file, taskId)
      clearRunning()
      scheduleArtifactRefresh()
    }

    if (state.status === 'failed' || (step === 'error' && status === 'failed')) {
      trackTaskResultOnce('task_failed', taskId, {
        task_type: state.task_type || appState.currentTaskType,
        error: (state.current_message || '').slice(0, 120),
      })
      clearRunning()
      taskFailed.value = true
      failedMessage.value = state.current_message || t('genFailedMsg')
    }
  } catch {
    // 网络错误静默，下次轮询重试
  }
}

function startPolling(taskId: string) {
  stopPolling()
  pollTimer = setInterval(() => pollTaskProgress(taskId), POLL_INTERVAL)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

function showResult(videoPath?: string, taskId?: string | null) {
  if (videoPath && taskId) {
    resultVideoVisible.value = true
    resultVideoSrc.value = '/api/video/' + taskId
  }
}

function setRunning(taskId: string) {
  appState.isTaskRunning = true
  appState.currentTaskId = taskId
}

function clearRunning() {
  appState.isTaskRunning = false
  appState.currentTaskId = null
  stopPolling()
}

export function useProgress() {
  return {
    progressVisible,
    progressPct,
    progressMessage,
    resultVideoVisible,
    resultVideoSrc,
    steps,
    stepStates,
    taskFailed,
    failedMessage,
    showProgress,
    pollTaskProgress,
    startPolling,
    stopPolling,
    showResult,
    setRunning,
    clearRunning,
    markStep,
    markCompletedStepsFromState,
    resetSteps,
    setProgressMessageHtml,
  }
}
