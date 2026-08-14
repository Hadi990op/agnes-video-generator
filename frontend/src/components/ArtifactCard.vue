<script setup lang="ts">
import { ref } from 'vue'
import { t } from '@/i18n'
import { useArtifacts } from '@/composables/useArtifacts'
import type { Artifact } from '@/types'

const props = defineProps<{ art: Artifact }>()

const {
  isRunning,
  artifactLabel,
  artifactIcon,
  artifactFileUrl,
  formatSize,
  toggleArtifactPreview,
  openImageModal,
  confirmDeleteArtifact,
} = useArtifacts()

const previewExpanded = ref(false)
const previewText = ref('')
const previewLoading = ref(false)

async function onPreviewClick(e: Event) {
  const el = e.currentTarget as HTMLElement
  if (!previewExpanded.value) {
    previewExpanded.value = true
    previewLoading.value = true
    previewText.value = ''
    try {
      const resp = await fetch(artifactFileUrl(props.art))
      let text = await resp.text()
      if (text.length > 2000) text = text.substring(0, 2000) + '\n...'
      previewText.value = text
    } catch (err: any) {
      previewText.value = 'Error: ' + err.message
    } finally {
      previewLoading.value = false
    }
  } else {
    previewExpanded.value = false
    previewText.value = ''
  }
  void el
}

async function onCopyPath() {
  const p = (props.art as any).abs_path || (props.art as any).path || ''
  if (!p) return
  try {
    await navigator.clipboard.writeText(p)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = p
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
}
</script>

<template>
  <div class="artifact-card flex items-start gap-3 p-3 bg-paper-2/30 rounded-xl border border-rule/40">
    <span class="text-lg mt-0.5 shrink-0">{{ artifactIcon(art) }}</span>
    <div class="flex-1 min-w-0">
      <div class="flex items-center gap-2 mb-1">
        <span class="text-xs text-ink-2 truncate">{{ artifactLabel(art) }}</span>
        <span class="text-xs text-muted shrink-0">{{ formatSize(art.size) }}</span>
      </div>

      <!-- 图片预览 -->
      <img
        v-if="art.category === 'image'"
        :src="artifactFileUrl(art)"
        class="max-h-36 rounded-lg cursor-pointer border border-rule/50"
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
        class="w-full rounded-lg border border-rule/50 bg-black"
        style="max-height: 260px"
      ></video>
      <!-- 音频预览 -->
      <audio v-else-if="art.category === 'audio'" :src="artifactFileUrl(art)" controls class="w-full" preload="metadata"></audio>
      <!-- 文本 / JSON 预览 -->
      <pre
        v-else
        class="text-xs text-muted max-h-24 overflow-auto bg-paper/70 p-2 rounded-lg border border-rule/40 cursor-pointer whitespace-pre-wrap"
        @click="onPreviewClick"
      >{{ previewExpanded ? (previewLoading ? t('loading') + '...' : previewText) : t('clickToPreview') }}</pre>

      <!-- 路径复制 -->
      <div
        v-if="(art as any).abs_path || (art as any).path"
        class="mt-1.5 text-[10px] text-muted font-mono truncate cursor-pointer hover:text-ink-2 transition"
        :title="t('copy')"
        @click="onCopyPath"
      >{{ (art as any).abs_path || (art as any).path }}</div>
    </div>

    <!-- 删除 -->
    <button
      v-if="art.deletable && !isRunning"
      class="text-xs px-2 py-1 bg-red-700/50 hover:bg-red-600 text-red-100 rounded transition shrink-0"
      :title="t('delete')"
      @click="confirmDeleteArtifact(art)"
    >
      ✕
    </button>
  </div>
</template>
