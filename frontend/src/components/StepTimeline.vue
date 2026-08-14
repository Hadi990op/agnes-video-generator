<script setup lang="ts">
import { computed } from 'vue'
import { t } from '@/i18n'
import { useProgress } from '@/composables/useProgress'

const props = defineProps<{ horizontal?: boolean }>()
const emit = defineEmits<{ (e: 'locate', stepKey: string): void }>()

const { steps, stepStates, awaitingCheckpoint } = useProgress()

// checkpoint -> 最近似的 step key（用于暂停时在时间线中高亮对应环节）
const CHECKPOINT_TO_STEP: Record<string, string> = {
  image_analysis: 'image_analysis',
  story: 'story',
  script: 'script',
  character_ref: 'character_ref',
  end_frame_prompts: 'end_frame_prompts',
  end_frame_gen: 'end_frame_gen',
  scenes: 'script',
  references: 'character_ref',
  videos: 'video_gen',
  audio: 'audio',
  subtitle: 'subtitle',
  final: 'concatenate',
}

const checkpointLabelKey: Record<string, string> = {
  image_analysis: 'cpImageAnalysis',
  story: 'cpStory',
  script: 'cpScript',
  character_ref: 'cpCharacterRef',
  end_frame_prompts: 'cpEndFramePrompts',
  end_frame_gen: 'cpEndFrameGen',
  scenes: 'cpScenes',
  references: 'cpReferences',
  videos: 'cpVideos',
  audio: 'cpAudio',
  subtitle: 'cpSubtitle',
  final: 'cpFinal',
}

type Item = { key: string; label: string; state: 'done' | 'running' | 'awaiting' | 'pending' }

const items = computed<Item[]>(() => {
  const cp = awaitingCheckpoint.value
  const highlightStep = cp ? CHECKPOINT_TO_STEP[cp] : ''
  const hasHighlight = cp && highlightStep && steps.value.some((s) => s.key === highlightStep)

  const list: Item[] = steps.value.map((s) => {
    let state: Item['state'] = stepStates.value[s.key] || 'pending'
    if (cp && hasHighlight && s.key === highlightStep) state = 'awaiting'
    return { key: s.key, label: t(s.labelKey), state }
  })

  // 暂停点无对应 step 时，在末尾追加独立条目
  if (cp && !hasHighlight) {
    list.push({ key: cp, label: t(checkpointLabelKey[cp] || cp), state: 'awaiting' })
  }
  return list
})

function onLocate(item: Item) {
  if (item.state !== 'pending') emit('locate', item.key)
}

function iconFor(state: Item['state']): string {
  if (state === 'done') return '✓'
  if (state === 'running') return '◉'
  if (state === 'awaiting') return '⏸'
  return '○'
}

function clsFor(state: Item['state']): string {
  if (state === 'done') return 'text-green-400'
  if (state === 'running') return 'text-accent'
  if (state === 'awaiting') return 'text-amber-400'
  return 'text-muted'
}
</script>

<template>
  <div v-if="!props.horizontal" class="glass-card rounded-2xl p-4">
    <div class="text-xs text-muted mb-3">{{ t('ppStages') }}</div>
    <div class="space-y-0.5">
      <button
        v-for="item in items"
        :key="item.key"
        class="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-lg text-left text-sm transition"
        :class="[
          item.state === 'awaiting' ? 'bg-amber-500/10 border border-amber-500/30' : 'hover:bg-paper-2/40 border border-transparent',
          item.state === 'running' ? 'bg-accent/5 border border-accent/20' : '',
        ]"
        @click="onLocate(item)"
      >
        <span
          class="w-4 text-center shrink-0"
          :class="[clsFor(item.state), item.state === 'running' ? 'animate-pulse' : '']"
        >{{ iconFor(item.state) }}</span>
        <span class="truncate" :class="item.state === 'awaiting' ? 'text-amber-400 font-medium' : ''">{{ item.label }}</span>
        <span v-if="item.state === 'awaiting'" class="ml-auto text-[10px] text-amber-400 shrink-0">{{ t('ppWaiting') }}</span>
      </button>
    </div>
  </div>

  <!-- 移动端：横向滚动胶囊 -->
  <div v-else class="flex gap-2 overflow-x-auto pb-2 -mx-1 px-1">
    <button
      v-for="item in items"
      :key="item.key"
      class="flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs whitespace-nowrap border transition"
      :class="[
        item.state === 'awaiting' ? 'bg-amber-500/10 border-amber-500/40 text-amber-400' : 'bg-paper/50 border-rule/60 text-ink-2',
        item.state === 'running' ? 'border-accent/40 text-accent' : '',
        item.state === 'done' ? 'text-green-400' : '',
      ]"
      @click="onLocate(item)"
    >
      <span :class="item.state === 'running' ? 'animate-pulse' : ''">{{ iconFor(item.state) }}</span>
      <span>{{ item.label }}</span>
    </button>
  </div>
</template>
