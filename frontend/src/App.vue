<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { t, LANGS, useI18n } from '@/i18n'
import { useTheme } from '@/composables/useTheme'
import { useToast } from '@/composables/useToast'
import { useConfig } from '@/composables/useConfig'
import { useVoice } from '@/composables/useVoice'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'
import { appState } from '@/store'
import ConfigPanel from '@/components/ConfigPanel.vue'
import CreatePanel from '@/components/CreatePanel.vue'
import TaskListPanel from '@/components/TaskListPanel.vue'
import ProgressPanel from '@/components/ProgressPanel.vue'
import VoicePickerModal from '@/components/VoicePickerModal.vue'
import Toast from '@/components/Toast.vue'

const { switchLang } = useI18n()
const { themeIcon, themeLabel, cycleTheme } = useTheme()
const { visible: toastVisible, message: toastMessage } = useToast()
const { loadModels, renderWorkspaces } = useConfig()
const { initVoiceSelector } = useVoice()
const { loadTaskList, startTaskListTimer, stopTaskListTimer } = useTasks()
const { showProgress, setRunning, startPolling } = useProgress()

const mainTab = ref<'create' | 'list'>('create')

function switchMainTab(tab: 'create' | 'list') {
  mainTab.value = tab
  if (tab === 'list') {
    loadTaskList()
    startTaskListTimer()
  } else {
    stopTaskListTimer()
  }
}

const isConfigLoaded = ref(false)

onMounted(async () => {
  try {
    const cfg = await fetch('/api/config').then((r) => r.json())
    if (cfg.api_key) {
      appState.apiKeySource = cfg.source
    }
    await renderWorkspaces()
    if (cfg.watermark !== undefined) {
      appState.watermarkEnabled = !!cfg.watermark.enabled
    }
    if (cfg.agnes_domain) {
      appState.agnesDomain = cfg.agnes_domain
    }
    await loadModels()
    isConfigLoaded.value = true
  } catch (e) {
    console.error('init config load error:', e)
  }

  try {
    await initVoiceSelector()
  } catch (e) {
    console.error('init voice selector error:', e)
  }

  // 自动重连运行中的任务
  autoReconnectRunningTask()
})

async function autoReconnectRunningTask() {
  try {
    const d = await fetch('/api/tasks').then((r) => r.json())
    const running = (d.tasks || []).find((t: any) => t.status === 'running' || t.status === 'queued')
    if (running) {
      appState.currentTaskType = running.task_type || 'creative'
      setRunning(running.task_id)
      appState.currentDirName = running.dir_name || running.task_id
      await showProgress(running.task_id, appState.currentDirName)
      await startPolling(running.task_id)
    }
  } catch {
    /* ignore */
  }
}
</script>

<template>
  <div class="flex justify-center gap-3 px-4">
    <!-- Left sidebar -->
    <aside class="hidden lg:block sticky top-[120px] self-start w-[130px] shrink-0 mt-8">
      <div class="sidebar-card">
        <div class="stitle">{{ t('adSupportTitle') }}</div>
        <p class="text-muted text-xs leading-relaxed mb-2">{{ t('adSupportDesc') }}</p>
        <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener">{{ t('adStar') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adStarDesc') }}</p>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adAdblock') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adAdblockDesc') }}</p>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener">{{ t('adClick') }}</a>
        <p class="text-muted text-xs px-1 -mt-0.5 mb-1">{{ t('adClickDesc') }}</p>
        <p class="text-muted text-xs mt-2 leading-relaxed">{{ t('adThanks') }}</p>
      </div>
    </aside>

    <!-- Main content -->
    <div class="max-w-4xl flex-1 min-w-0 py-8">
      <!-- Header -->
      <div class="text-center mb-10">
        <div class="flex items-center justify-end gap-2 mb-5">
          <button
            class="glass-input rounded-lg px-3 py-1.5 text-sm cursor-pointer text-ink flex items-center gap-1.5 hover:border-accent/40 transition"
            :title="themeLabel"
            :aria-label="themeLabel"
            @click="cycleTheme"
          >
            <svg class="w-4 h-4 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.8" :d="themeIcon"></path>
            </svg>
            <span class="text-xs whitespace-nowrap">{{ themeLabel }}</span>
          </button>
          <select
            class="glass-input rounded-lg px-3 py-1.5 text-sm cursor-pointer text-ink"
            @change="switchLang(($event.target as HTMLSelectElement).value)"
          >
            <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</option>
          </select>
        </div>
        <h1 class="text-4xl font-bold text-ink" style="position: relative; z-index: 0">Agnes Video Generator</h1>
        <p class="text-muted mt-2 text-sm tracking-wide">{{ t('subtitle') }}</p>
      </div>

      <!-- Resource links -->
      <nav class="flex justify-center items-center gap-4 mb-8 text-xs tracking-wide">
        <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="flex items-center gap-1 text-accent hover:text-ink transition-colors">🎬 Demo</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">🏠 Home</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">📖 Guides</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">❓ FAQ</a>
        <span class="text-ink/5 select-none">·</span>
        <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="flex items-center gap-1 text-muted hover:text-ink-2 transition-colors">📖 GitHub</a>
      </nav>

      <!-- Config Panel -->
      <ConfigPanel />

      <!-- Main Tabs -->
      <div class="flex gap-2 mb-6">
        <button
          class="px-5 py-2.5 rounded-lg text-sm font-medium transition"
          :class="mainTab === 'create' ? 'tab-active' : 'tab-inactive'"
          @click="switchMainTab('create')"
        >
          {{ t('tabCreate') }}
        </button>
        <button
          class="px-5 py-2.5 rounded-lg text-sm font-medium transition"
          :class="mainTab === 'list' ? 'tab-active' : 'tab-inactive'"
          @click="switchMainTab('list')"
        >
          {{ t('tabList') }}
        </button>
      </div>

      <!-- Create Panel -->
      <div v-show="mainTab === 'create'">
        <CreatePanel />
      </div>

      <!-- List Panel -->
      <div v-show="mainTab === 'list'">
        <TaskListPanel />
      </div>

      <!-- Progress Panel -->
      <ProgressPanel />

      <!-- Footer -->
      <footer class="text-center pb-8">
        <div class="border-t border-rule/30 pt-8 mt-4">
          <p class="text-xs text-muted mb-3">{{ t('moreResources') }}</p>
          <div class="flex justify-center flex-wrap gap-x-5 gap-y-2 text-xs">
            <a href="https://video.lichuanyang.top" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('projectHome') }}</a>
            <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('onlineDemo') }}</a>
            <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('usageGuide') }}</a>
            <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('faqTitle') }}</a>
            <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('apiDocs') }}</a>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('appScenarios') }}</a>
            <a href="https://github.com/lcy362/agnes-video-generator" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">📖 GitHub</a>
          </div>
        </div>
      </footer>
    </div>

    <!-- Right sidebar -->
    <aside class="hidden lg:block sticky top-[120px] self-start w-[115px] shrink-0 mt-8">
      <div class="sidebar-card">
        <div class="stitle">{{ t('quickLinks') }}</div>
        <a href="https://video.lichuanyang.top/demo" target="_blank" rel="noopener">{{ t('onlineDemo') }}</a>
        <a href="https://video.lichuanyang.top/guides/prompt-tips" target="_blank" rel="noopener">{{ t('promptTips') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('modelOverview') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('apiCall') }}</a>
        <a href="https://video.lichuanyang.top/faq" target="_blank" rel="noopener">{{ t('faqTitle') }}</a>
        <a href="https://video.lichuanyang.top/api-docs" target="_blank" rel="noopener">{{ t('apiDocs') }}</a>
        <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener">{{ t('appScenarios') }}</a>
      </div>
    </aside>
  </div>

  <!-- Voice Picker Modal -->
  <VoicePickerModal />

  <!-- Toast -->
  <Toast :visible="toastVisible" :message="toastMessage" />
</template>
