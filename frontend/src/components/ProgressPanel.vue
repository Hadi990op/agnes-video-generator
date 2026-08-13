<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'
import { useArtifacts } from '@/composables/useArtifacts'
import { useTasks } from '@/composables/useTasks'

const {
  progressVisible,
  progressPct,
  progressMessage,
  resultVideoVisible,
  resultVideoSrc,
  steps,
  stepStates,
  taskFailed,
  failedMessage,
  clearRunning,
} = useProgress()

const {
  artifactsAreaVisible,
  artifactGroups,
  isRunning,
  imageModalUrl,
  stepLabelMap,
  loadArtifacts,
  artifactLabel,
  artifactIcon,
  artifactFileUrl,
  formatSize,
  toggleArtifactPreview,
  openImageModal,
  closeImageModal,
  confirmDeleteArtifact,
} = useArtifacts()

const { stopTaskById, loadTaskList } = useTasks()

const detailState = computed(() => appState.currentTaskId)

async function stopCurrentTask() {
  if (!appState.currentTaskId) return
  if (!confirm(t('stopConfirm'))) return
  await stopTaskById(appState.currentTaskId)
}

function stepIconClass(status: string): string {
  if (status === 'done') return 'w-5 h-5 flex items-center justify-center rounded-full bg-green-900 text-green-300 text-xs'
  if (status === 'running') return 'w-5 h-5 flex items-center justify-center rounded-full bg-paper-3 text-accent text-xs animate-pulse-dot'
  return 'w-5 h-5 flex items-center justify-center rounded-full bg-paper-2 text-xs'
}

function stepLabelClass(status: string): string {
  if (status === 'done') return 'step-label text-green-400'
  if (status === 'running') return 'step-label text-accent'
  return 'step-label text-muted'
}

function stepIcon(status: string): string {
  if (status === 'done') return '✓'
  if (status === 'running') return '◉'
  return '○'
}
</script>

<template>
  <div v-if="progressVisible" class="glass-card rounded-2xl p-6 mt-6">
    <div class="flex items-center justify-between mb-4">
      <h2 class="text-lg font-semibold text-accent">{{ t('progress') }}</h2>
      <div class="flex items-center gap-3">
        <span class="text-sm text-muted">{{ progressPct }}%</span>
        <button
          v-if="appState.isTaskRunning"
          class="text-xs px-3 py-1.5 bg-red-700/80 hover:bg-red-600 text-red-100 rounded-lg transition"
          @click="stopCurrentTask"
        >
          {{ t('stopTask') }}
        </button>
      </div>
    </div>

    <div class="w-full bg-paper-2/50 rounded-full h-2.5 mb-6 overflow-hidden">
      <div class="bg-accent h-2.5 rounded-full transition-all duration-500" :style="{ width: progressPct + '%' }"></div>
    </div>

    <div class="space-y-2">
      <div v-for="s in steps" :key="s.key" class="step-item flex items-center gap-3 text-sm">
        <span class="step-icon" :class="stepIconClass(stepStates[s.key] || 'pending')">{{ stepIcon(stepStates[s.key] || 'pending') }}</span>
        <span :class="stepLabelClass(stepStates[s.key] || 'pending')">{{ t(s.labelKey) }}</span>
      </div>
    </div>

    <p class="mt-4 text-xs text-muted">
      <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="hover:text-accent transition-colors">{{ t('waitTip') }}</a>
    </p>

    <!-- 失败信息 -->
    <div v-if="taskFailed" class="mt-4">
      <div class="p-4 bg-red-950 border border-red-800 rounded-lg space-y-2">
        <p class="text-red-400 font-medium">{{ t('genFailed') }}</p>
        <p class="text-muted text-xs">{{ failedMessage || t('genFailedMsg') }}</p>
      </div>
    </div>

    <!-- 进度消息（HTML 渲染，来自后端安全文案） -->
    <div v-else class="mt-4 text-sm text-muted" v-html="progressMessage"></div>

    <!-- 中间产物面板 -->
    <div v-if="artifactsAreaVisible" class="mt-4 p-4 bg-paper/30 rounded-lg border border-rule/50">
      <div class="flex items-center justify-between mb-3">
        <h3 class="text-sm font-medium text-accent">{{ t('artTitle') }}</h3>
        <button class="text-xs text-muted hover:text-ink-2 transition" @click="loadArtifacts">↻</button>
      </div>
      <div class="space-y-2 max-h-96 overflow-y-auto">
        <div v-for="g in artifactGroups" :key="g.stepKey" class="mb-3">
          <div class="text-xs text-muted mb-1">{{ t(stepLabelMap[g.stepKey] || g.stepKey) }}</div>
          <div class="space-y-1.5">
            <div v-for="art in g.items" :key="art.artifact_id" class="artifact-card flex items-start gap-2 p-2 bg-paper-2/30 rounded">
              <span class="text-sm mt-0.5">{{ artifactIcon(art) }}</span>
              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2 mb-1">
                  <span class="text-xs text-ink-2">{{ artifactLabel(art) }}</span>
                  <span class="text-xs text-muted">{{ formatSize(art.size) }}</span>
                </div>
                <!-- 图片预览 -->
                <img
                  v-if="art.category === 'image'"
                  :src="artifactFileUrl(art)"
                  class="max-h-32 rounded cursor-pointer border border-rule/50"
                  loading="lazy"
                  @click="openImageModal(artifactFileUrl(art))"
                />
                <!-- 视频预览 -->
                <video
                  v-else-if="art.category === 'video'"
                  :src="artifactFileUrl(art)"
                  controls
                  playsinline
                  preload="metadata"
                  class="w-full rounded border border-rule/50 bg-black"
                  style="max-height: 360px; min-height: 200px"
                ></video>
                <!-- 音频预览 -->
                <audio v-else-if="art.category === 'audio'" :src="artifactFileUrl(art)" controls class="w-full" preload="metadata"></audio>
                <!-- 文本预览 -->
                <pre
                  v-else
                  class="text-xs text-muted max-h-24 overflow-auto bg-paper/70 p-2 rounded border border-rule cursor-pointer"
                  @click="toggleArtifactPreview(art, $event.currentTarget as HTMLElement)"
                >{{ t('clickToPreview') }}</pre>
              </div>
              <button
                v-if="art.deletable && !isRunning"
                class="text-xs px-2 py-1 bg-red-700/50 hover:bg-red-600 text-red-100 rounded transition flex-shrink-0"
                :title="t('delete')"
                @click="confirmDeleteArtifact(art)"
              >
                ✕
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 结果视频 -->
    <div v-if="resultVideoVisible" class="mt-4 p-4 glass-card rounded-lg">
      <p class="text-green-400 text-sm font-medium mb-2">{{ t('videoComplete') }}</p>
      <video :src="resultVideoSrc" controls class="w-full rounded-lg max-h-96"></video>
      <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-xs">
        <span>🎉</span>
        <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('doneTipTiktok') }}</a>
        <span class="text-ink/10 select-none">·</span>
        <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('doneTipMore') }}</a>
      </div>
    </div>
  </div>

  <!-- 图片放大弹窗 -->
  <div v-if="imageModalUrl" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-pointer" @click="closeImageModal">
    <img :src="imageModalUrl" class="max-w-[90vw] max-h-[90vh] rounded-lg" />
  </div>
</template>
