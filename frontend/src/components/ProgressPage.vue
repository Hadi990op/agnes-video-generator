<script setup lang="ts">
import { onMounted, onUnmounted, ref, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import { useProgress } from '@/composables/useProgress'
import { useArtifacts } from '@/composables/useArtifacts'
import { useNavigation } from '@/composables/useNavigation'
import ProgressHeader from './ProgressHeader.vue'
import StepTimeline from './StepTimeline.vue'
import ArtifactCard from './ArtifactCard.vue'
import CheckpointDetail from './CheckpointDetail.vue'

const {
  progressPct,
  progressMessage,
  resultVideoVisible,
  resultVideoSrc,
  steps,
  stepStates,
  taskFailed,
  failedMessage,
  awaitingCheckpoint,
  mountProgressPage,
  unmountProgressPage,
} = useProgress()

const {
  artifactsAreaVisible,
  artifactGroups,
  imageModalUrl,
  stepLabelMap,
  closeImageModal,
} = useArtifacts()

const { goBack } = useNavigation()

// 产物流按执行顺序排列（steps 顺序优先，未知 step 保持后端相对顺序）
const orderedGroups = computed(() => {
  const order = steps.value.map((s) => s.key)
  const map: Record<string, (typeof artifactGroups.value)[0]> = {}
  artifactGroups.value.forEach((g) => {
    if (!map[g.stepKey]) map[g.stepKey] = g
  })
  const keys = Object.keys(map)
  keys.sort((a, b) => {
    const ia = order.indexOf(a)
    const ib = order.indexOf(b)
    if (ia === -1 && ib === -1) return 0
    if (ia === -1) return 1
    if (ib === -1) return -1
    return ia - ib
  })
  return keys.map((k) => map[k])
})

// 折叠状态：默认已完成环节折叠为一行（产物流只聚焦进行中 + 最新）
const collapsed = ref<Record<string, boolean>>({})
function toggleCollapse(key: string) {
  collapsed.value[key] = !collapsed.value[key]
}
function isCollapsed(key: string): boolean {
  if (key in collapsed.value) return collapsed.value[key]
  return stepStates.value[key] === 'done'
}

// 步骤定位：点击时间线滚动到对应产物分组
function scrollToStep(stepKey: string) {
  const el = document.getElementById('artifact-group-' + stepKey)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

onMounted(async () => {
  const taskId = appState.progressTaskId
  if (!taskId) return
  await mountProgressPage(taskId, appState.currentDirName)
})

onUnmounted(() => {
  unmountProgressPage()
})
</script>

<template>
  <div class="progress-page min-h-screen">
    <ProgressHeader />

    <div class="max-w-6xl mx-auto px-4 py-6 lg:flex lg:gap-6">
      <!-- 左侧环节状态列表（宽屏） -->
      <aside class="hidden lg:block w-[240px] shrink-0">
        <StepTimeline @locate="scrollToStep" />
      </aside>

      <!-- 主工作台 -->
      <main class="flex-1 min-w-0">
        <!-- 移动端环节胶囊条 -->
        <div class="lg:hidden mb-4">
          <StepTimeline horizontal @locate="scrollToStep" />
        </div>

        <!-- 状态区 -->
        <div class="glass-card rounded-2xl p-5 mb-4">
          <div class="flex items-center justify-between mb-2">
            <span class="text-sm text-muted">{{ t('progress') }}</span>
            <span class="text-sm text-accent font-medium">{{ progressPct }}%</span>
          </div>
          <div class="w-full bg-paper-2/50 rounded-full h-2.5 overflow-hidden">
            <div class="bg-accent h-2.5 rounded-full transition-all duration-500" :style="{ width: progressPct + '%' }"></div>
          </div>

          <!-- 失败信息 -->
          <div v-if="taskFailed" class="mt-4 p-4 bg-red-950 border border-red-800 rounded-lg space-y-2">
            <p class="text-red-400 font-medium">{{ t('genFailed') }}</p>
            <p class="text-muted text-xs">{{ failedMessage || t('genFailedMsg') }}</p>
          </div>
          <!-- 进度消息（HTML 渲染，来自后端安全文案） -->
          <div v-else class="mt-4 text-sm text-muted" v-html="progressMessage"></div>
        </div>

        <!-- 产物流：逐步追加（按环节分组，已完成折叠） -->
        <div v-if="artifactsAreaVisible" class="space-y-3">
          <div
            v-for="g in orderedGroups"
            :id="'artifact-group-' + g.stepKey"
            :key="g.stepKey"
            class="artifact-group glass-card rounded-2xl overflow-hidden"
          >
            <button
              class="w-full flex items-center gap-3 px-4 py-3 text-left transition hover:bg-paper-2/30"
              @click="toggleCollapse(g.stepKey)"
            >
              <span class="text-sm transition-transform" :class="isCollapsed(g.stepKey) ? '' : 'rotate-90'">▸</span>
              <span class="text-sm font-medium text-ink-2">{{ t(stepLabelMap[g.stepKey] || g.stepKey) }}</span>
              <span class="text-xs text-muted">{{ g.items.length }} 项</span>
              <span class="ml-auto text-xs text-muted">{{ isCollapsed(g.stepKey) ? t('ppExpand') : t('ppCollapse') }}</span>
            </button>

            <div v-show="!isCollapsed(g.stepKey)" class="px-4 pb-4 space-y-2">
              <ArtifactCard v-for="art in g.items" :key="art.artifact_id" :art="art" />
            </div>
          </div>
        </div>

        <!-- 暂停审查区：紧跟最新产物（就近操作） -->
        <CheckpointDetail
          v-if="awaitingCheckpoint && appState.currentTaskId"
          :task-id="appState.currentTaskId"
          :checkpoint="awaitingCheckpoint"
        />

        <!-- 结果视频 -->
        <div v-if="resultVideoVisible" class="mt-4 p-4 glass-card rounded-2xl">
          <p class="text-green-400 text-sm font-medium mb-2">{{ t('videoComplete') }}</p>
          <video :src="resultVideoSrc" controls class="w-full rounded-lg max-h-96"></video>
          <div class="flex flex-wrap items-center gap-x-4 gap-y-1 mt-3 text-xs">
            <span>🎉</span>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-accent hover:text-ink transition-colors">{{ t('doneTipTiktok') }}</a>
            <span class="text-ink/10 select-none">·</span>
            <a href="https://video.lichuanyang.top/learn" target="_blank" rel="noopener" class="text-muted hover:text-ink-2 transition-colors">{{ t('doneTipMore') }}</a>
          </div>
        </div>
      </main>
    </div>

    <!-- 图片放大弹窗 -->
    <div v-if="imageModalUrl" class="fixed inset-0 z-50 flex items-center justify-center bg-black/80 cursor-pointer" @click="closeImageModal">
      <img :src="imageModalUrl" class="max-w-[90vw] max-h-[90vh] rounded-lg" />
    </div>
  </div>
</template>
