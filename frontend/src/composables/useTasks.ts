import { ref } from 'vue'
import { appState } from '@/store'
import * as api from '@/api'
import { t } from '@/i18n'
import { useToast } from './useToast'
import { useGa } from './useGa'
import { useProgress } from './useProgress'
import type { TaskListItem, TaskState } from '@/types'

const { showToast } = useToast()
const { trackEvent } = useGa()
const { setRunning, showProgress, startPolling } = useProgress()

const tasks = ref<TaskListItem[]>([])
const loading = ref(false)
let taskListTimer: ReturnType<typeof setInterval> | null = null

async function loadTaskList() {
  try {
    const d = await api.getTasks()
    tasks.value = d.tasks || []
  } catch (e) {
    loading.value = false
  }
}

function startTaskListTimer() {
  if (taskListTimer) return
  taskListTimer = setInterval(loadTaskList, 5000)
}

function stopTaskListTimer() {
  if (taskListTimer) {
    clearInterval(taskListTimer)
    taskListTimer = null
  }
}

async function viewTask(taskId: string) {
  try {
    const state = await api.getTask(taskId)
    appState.currentTaskType = state.task_type || 'creative'
    return state
  } catch (e: any) {
    alert(t('failLoad') + ': ' + e.message)
    return null
  }
}

async function viewRunningTask(taskId: string) {
  const state = await viewTask(taskId)
  if (!state) return
  setRunning(taskId)
  await showProgress(taskId, null)
  await startPolling(taskId)
}

async function resumeTask(taskId: string) {
  try {
    const d = await api.resumeTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failResume'))
    let taskType = 'creative'
    try {
      const st = await api.getTask(taskId)
      taskType = st.task_type || 'creative'
    } catch {
      /* ignore */
    }
    appState.currentTaskType = taskType
    setRunning(taskId)
    appState.currentDirName = d.dir_name
    await showProgress(taskId, d.dir_name)
    await startPolling(taskId)
    showToast(t('resumed'), 5000)
  } catch (e: any) {
    alert(t('failResume') + ': ' + e.message)
  }
}

async function stopTaskById(taskId: string) {
  if (!confirm(t('stopConfirmById'))) return
  try {
    const d = await api.stopTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failStop'))
    trackEvent('task_stopped', { task_type: appState.currentTaskType || '', source: 'list' })
    showToast(t('stoppedById'), 3000)
    loadTaskList()
  } catch (e: any) {
    alert(t('failStop') + ': ' + e.message)
  }
}

async function deleteTaskById(taskId: string) {
  if (!confirm(t('deleteTaskConfirm'))) return
  try {
    const d = await api.deleteTask(taskId)
    if (!d.ok) throw new Error(d.detail || t('failDelete'))
    trackEvent('task_deleted', { task_type: appState.currentTaskType || '', source: 'list' })
    showToast(t('deletedTask'), 3000)
    loadTaskList()
  } catch (e: any) {
    alert(t('failDelete') + ': ' + e.message)
  }
}

// 详情展示（由组件消费）
const detailState = ref<TaskState | null>(null)

function showTaskDetail(taskId: string, state: TaskState) {
  detailState.value = state
}

export function useTasks() {
  return {
    tasks,
    loading,
    detailState,
    loadTaskList,
    startTaskListTimer,
    stopTaskListTimer,
    viewTask,
    viewRunningTask,
    resumeTask,
    stopTaskById,
    deleteTaskById,
    showTaskDetail,
  }
}
