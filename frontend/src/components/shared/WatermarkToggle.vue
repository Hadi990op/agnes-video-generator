<script setup lang="ts">
import { t } from '@/i18n'
import { appState } from '@/store'
import { useConfig } from '@/composables/useConfig'

const { toggleWatermark } = useConfig()

function onChange(e: Event) {
  toggleWatermark((e.target as HTMLInputElement).checked)
}
</script>

<template>
  <div class="flex items-center justify-between px-1 py-2 mb-4">
    <p class="text-xs text-muted leading-relaxed mr-3">{{ t('watermarkPromo') }}</p>
    <label class="relative inline-flex items-center cursor-pointer flex-shrink-0" title="Video Watermark">
      <input
        type="checkbox"
        class="watermark-toggle sr-only peer"
        :checked="appState.watermarkEnabled"
        @change="onChange"
      />
      <div class="w-10 h-5 bg-paper-3 peer-focus:outline-none rounded-full peer peer-checked:after:translate-x-full after:content-[''] after:absolute after:top-[2px] after:start-[2px] after:bg-rule after:rounded-full after:h-4 after:w-4 after:transition-all peer-checked:bg-accent"></div>
    </label>
  </div>
</template>
