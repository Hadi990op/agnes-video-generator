<script setup lang="ts">
import { computed } from 'vue'
import { t, LANGS, useI18n } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'
import { useTasks } from '@/composables/useTasks'
import { useNavigation } from '@/composables/useNavigation'

const { switchLang } = useI18n()
const { progressPct, awaitingCheckpoint, taskFailed, needsResume, resumeTask } = useProgress()
const { stopTaskById, switchMode } = useTasks()
const { goBack, goHome } = useNavigation()

const taskId = computed(() => appState.currentTaskId || appState.progressTaskId || '')
const dirName = computed(() => appState.currentDirName || '')

const typeLabelKey: Record<string, string> = {
  simple: 'typeSimple',
  creative: 'typeCreative',
  manuscript: 'typeManuscript',
  anchor: 'typeAnchor',
  poetry: 'typePoetry',
  image: 'typeImage',
}

const statusInfo = computed(() => {
  if (taskFailed.value) return { key: 'statusFailed', cls: 'text-red-400 bg-red-950/60 border-red-800/60' }
  if (needsResume.value) return { key: 'statusNeedsResume', cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30' }
  if (awaitingCheckpoint.value) return { key: 'statusAwaitingUser', cls: 'text-amber-400 bg-amber-500/10 border-amber-500/30' }
  if (appState.isTaskRunning || progressPct.value > 0 && progressPct.value < 100) {
    return { key: 'statusRunning', cls: 'text-yellow-400 bg-yellow-500/10 border-yellow-500/30' }
  }
  return { key: 'statusCompleted', cls: 'text-emerald-400 bg-emerald-500/10 border-emerald-500/30' }
})

function onBack() {
  goBack()
}

function onHome() {
  goHome()
}

async function onStop() {
  if (taskId.value) await stopTaskById(taskId.value)
}

async function onResume() {
  if (taskId.value) await resumeTask(taskId.value)
}

async function onSwitchAuto() {
  if (taskId.value) await switchMode(taskId.value, 'auto')
}
</script>

<template>
  <header class="sticky top-0 z-40 bg-paper border-b border-rule/40">
    <div class="max-w-6xl mx-auto px-4 py-3 flex items-center gap-3">
      <button
        class="flex items-center gap-1 text-sm text-ink-2 hover:text-accent transition rounded-lg px-2 py-1 -ml-2"
        @click="onBack"
      >
        <span class="text-lg leading-none">←</span>
        <span class="text-xs">{{ t('progressBack') }}</span>
      </button>

      <a
        href="#"
        class="flex items-center gap-1 text-sm text-accent hover:text-ink transition rounded-lg px-2 py-1"
        @click.prevent="onHome"
      >
        <span class="text-lg leading-none">🏠</span>
        <span class="text-xs">{{ t('goHome') }}</span>
      </a>

      <div class="flex items-center gap-2 min-w-0">
        <span class="text-xs px-2 py-0.5 rounded-full bg-accent/15 text-accent shrink-0">
          {{ t(typeLabelKey[appState.currentTaskType] || '') || appState.currentTaskType }}
        </span>
        <span class="text-sm font-medium truncate text-ink">{{ t('task_') }}: {{ taskId }}</span>
        <span v-if="dirName" class="text-xs text-muted font-mono truncate hidden md:inline">{{ dirName }}</span>
      </div>

      <div class="ml-auto flex items-center gap-2 shrink-0">
        <select
          class="glass-input rounded-lg px-2 py-1.5 text-xs cursor-pointer text-ink"
          :title="t('langSwitch')"
          @change="switchLang(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="l in LANGS" :key="l.code" :value="l.code">{{ l.label }}</option>
        </select>
        <span class="text-xs px-2.5 py-1 rounded-full border" :class="statusInfo.cls">
          {{ t(statusInfo.key) }}
        </span>
        <button
          v-if="needsResume"
          class="text-xs px-3 py-1.5 bg-accent text-accent-ink rounded-lg transition"
          @click="onResume"
        >
          ▶ {{ t('resumeTaskBtn') }}
        </button>
        <button
          v-if="awaitingCheckpoint"
          class="text-xs px-3 py-1.5 border border-rule text-ink-2 rounded-lg transition hover:border-accent/40"
          @click="onSwitchAuto"
        >
          ⚡ {{ t('switchToAuto') }}
        </button>
        <button
          v-if="appState.isTaskRunning"
          class="text-xs px-3 py-1.5 bg-red-700/80 hover:bg-red-600 text-red-100 rounded-lg transition"
          @click="onStop"
        >
          {{ t('stopTask') }}
        </button>
      </div>
    </div>
  </header>
</template>
