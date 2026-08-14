<script setup lang="ts">
import { ref, computed } from 'vue'
import { t } from '@/i18n'
import { appState } from '@/store'
import * as api from '@/api'
import { useTasks } from '@/composables/useTasks'
import { useProgress } from '@/composables/useProgress'

const props = defineProps<{ taskId: string; checkpoint: string }>()

const { switchMode, loadTaskList } = useTasks()
const { startPolling, setRunning } = useProgress()

// 三卡片选择
const activeCard = ref<'ai' | 'self' | 'agent'>('ai')
const aiRequest = ref('')
const aiLoading = ref(false)
const aiResult = ref<any>(null)
const checkpointData = ref<any>(null)
const loadingData = ref(false)

const impactData = ref<any>(null)
const impactLoading = ref(false)
const confirming = ref(false)

const checkpointLabel = computed(() => {
  const map: Record<string, string> = { scenes: 'cpScenes', references: 'cpReferences', videos: 'cpVideos', audio: 'cpAudio', subtitle: 'cpSubtitle', final: 'cpFinal' }
  return t(map[props.checkpoint] || props.checkpoint)
})

// 拉取检查点产物元数据（驱动 AI 修改目标与"自己改"路径清单）
async function loadCheckpoint() {
  loadingData.value = true
  try {
    const d = await api.getCheckpoint(props.taskId, props.checkpoint)
    if (d.ok) checkpointData.value = d
  } catch {
    /* ignore */
  } finally {
    loadingData.value = false
  }
}
loadCheckpoint()

// ── 通道 1：AI 帮我改（P1 已实现后端；ai-modify 为 P1.5，此处先做前端调用适配）──
async function runAiModify() {
  const req = aiRequest.value.trim()
  if (!req) return
  aiLoading.value = true
  aiResult.value = null
  try {
    // 当前检查点第一个可编辑产物作为修改目标（简化：通道 1 一期由产物矩阵驱动）
    const arts = (checkpointData.value?.artifacts || []).filter((a: any) => a.deletable)
    const target = arts[0]
    if (!target) throw new Error(t('noEditableArtifact'))
    // 先按 impact 预计算
    const imp = await api.getImpact(props.taskId, props.checkpoint, [target.artifact_id])
    impactData.value = imp
    aiResult.value = { target: target.artifact_id, preview: null }
  } catch (e: any) {
    alert(e.message || t('aiModifyFailed'))
  } finally {
    aiLoading.value = false
  }
}

// ── 影响预计算 ──
async function previewImpact(modifiedIds: string[]) {
  impactLoading.value = true
  try {
    impactData.value = await api.getImpact(props.taskId, props.checkpoint, modifiedIds)
  } finally {
    impactLoading.value = false
  }
}

// ── 确认并继续（approve）──
async function doApprove(modifiedIds: string[], paramUpdates: Record<string, any> = {}) {
  confirming.value = true
  try {
    const d = await api.approveCheckpoint(props.taskId, props.checkpoint, modifiedIds, paramUpdates, true)
    if (!d.ok) throw new Error(d.detail || t('failContinue'))
    // 恢复执行
    setRunning(props.taskId)
    await startPolling(props.taskId)
    loadTaskList()
  } catch (e: any) {
    alert(e.message || t('failContinue'))
  } finally {
    confirming.value = false
  }
}

async function copyText(text: string) {
  if (!text) return
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}

// ── 通道 2 / 3：直接确认（approve 不传 modified → 仅确认继续）──
async function confirmNoChange() {
  await doApprove([])
}

// ── 切回自动并继续 ──
async function switchToAutoAndRun() {
  await switchMode(props.taskId, 'auto')
}

// ── 重新生成当前检查点 ──
async function regen() {
  confirming.value = true
  try {
    const d = await api.regenCheckpoint(props.taskId, props.checkpoint)
    if (!d.ok) throw new Error(d.detail || t('failRegen'))
    setRunning(props.taskId)
    await startPolling(props.taskId)
  } catch (e: any) {
    alert(e.message || t('failRegen'))
  } finally {
    confirming.value = false
  }
}
</script>

<template>
  <div class="mt-4 p-4 bg-paper/30 rounded-2xl border border-amber-500/30">
    <div class="flex items-center justify-between mb-3">
      <h3 class="text-sm font-semibold text-amber-400">
        ⏸ {{ t('awaitingUser') }} · {{ t('checkpointTitle') }}: {{ checkpointLabel }}
      </h3>
      <div class="flex gap-2">
        <button class="text-xs px-2.5 py-1.5 bg-accent text-accent-ink rounded-lg transition" @click="regen" :disabled="confirming">
          {{ t('regenCurrent') }}
        </button>
        <button class="text-xs px-2.5 py-1.5 border border-rule text-ink-2 rounded-lg transition hover:border-accent/40" @click="switchToAutoAndRun">
          ⚡ {{ t('switchToAuto') }}
        </button>
      </div>
    </div>

    <p class="text-xs text-muted mb-3">{{ t('awaitingUserTip') }}</p>

    <!-- 三卡片 -->
    <div class="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
      <button class="p-3 rounded-xl border text-left transition" :class="activeCard === 'ai' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'" @click="activeCard = 'ai'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleAi') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleAiDesc') }}</div>
      </button>
      <button class="p-3 rounded-xl border text-left transition" :class="activeCard === 'self' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'" @click="activeCard = 'self'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleSelf') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleSelfDesc') }}</div>
      </button>
      <button class="p-3 rounded-xl border text-left transition" :class="activeCard === 'agent' ? 'border-accent bg-accent/10' : 'border-rule bg-paper-2/30 hover:border-accent/40'" @click="activeCard = 'agent'">
        <div class="text-sm font-medium text-ink-2">{{ t('handleAgent') }}</div>
        <div class="text-xs text-muted mt-0.5">{{ t('handleAgentDesc') }}</div>
      </button>
    </div>

    <!-- 通道 1 面板 -->
    <div v-if="activeCard === 'ai'" class="space-y-3">
      <div>
        <label class="block text-xs text-muted mb-1">{{ t('aiModifyRequest') }}</label>
        <textarea v-model="aiRequest" rows="2" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink resize-y" :placeholder="t('aiModifyRequestPlaceholder')"></textarea>
      </div>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition disabled:opacity-50" :disabled="aiLoading" @click="runAiModify">
        {{ aiLoading ? t('aiModifyApplying') : t('aiModifyStart') }}
      </button>
      <!-- 影响预计算展示（修改前提示） -->
      <div v-if="impactData" class="p-3 rounded-lg bg-paper/50 border border-rule/60 space-y-1.5">
        <p class="text-xs font-medium text-red-400">{{ t('impactTitle') }}: {{ (impactData.affected || []).length }}</p>
        <ul class="text-xs text-muted space-y-0.5 max-h-24 overflow-auto">
          <li v-for="a in impactData.affected || []" :key="a">• {{ a }}</li>
        </ul>
        <p v-if="impactData.retained?.length" class="text-xs text-emerald-400">{{ t('impactRetained') }}: {{ (impactData.retained || []).length }}</p>
      </div>
      <div class="flex gap-2">
        <button v-if="impactData" class="text-xs px-4 py-2 bg-red-700 text-red-100 rounded-lg transition" :disabled="confirming" @click="doApprove([aiResult?.target])">
          {{ confirming ? t('submitting') : t('impactConfirm') }}
        </button>
        <button v-if="impactData" class="text-xs px-4 py-2 border border-rule text-ink-2 rounded-lg transition" @click="impactData = null">{{ t('impactCancel') }}</button>
      </div>
    </div>

    <!-- 通道 2 面板 -->
    <div v-else-if="activeCard === 'self'" class="space-y-3">
      <div v-for="art in checkpointData?.artifacts || []" :key="art.artifact_id" class="text-xs">
        <span class="text-muted">{{ art.label_key || art.artifact_id }}:</span>
        <code class="block text-ink-2 bg-paper-2 px-2 py-1 rounded mt-0.5 break-all cursor-pointer hover:border-accent/40 border border-transparent"
          :title="t('copy')"
          @click="copyText(art.abs_path || art.path || '')"
        >{{ art.abs_path || art.path || '' }}</code>
      </div>
      <p class="text-xs text-muted">{{ t('selfEditAffected') }}: {{ t('selfEditAffectedHint') }}</p>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition" @click="confirmNoChange">
        {{ t('selfEditDone') }}
      </button>
    </div>

    <!-- 通道 3 面板 -->
    <div v-else class="space-y-3">
      <p class="text-xs text-muted">{{ t('agentCommand') }}:</p>
      <code class="block text-xs bg-black/40 text-green-300 px-3 py-2 rounded-lg mb-2 break-all">{{ 'cd ' + (checkpointData?.working_dir || '') + ' && opencode' }}</code>
      <p class="text-xs text-muted">{{ t('agentPrompt') }}:</p>
      <textarea rows="3" class="w-full glass-input rounded-lg px-3 py-2 text-sm text-ink font-mono text-xs resize-y" :value="t('agentPromptTemplate').replace('{dir}', checkpointData?.working_dir || '')" readonly></textarea>
      <button class="text-xs px-4 py-2 bg-accent text-accent-ink rounded-lg transition" @click="confirmNoChange">
        {{ t('agentDone') }}
      </button>
    </div>
  </div>
</template>
