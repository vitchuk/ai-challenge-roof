<script setup lang="ts">
import type { RetrieveDebug, Source } from '../types'

defineProps<{ sources: Source[]; debug: RetrieveDebug | null }>()

function scorePercent(score: number): number {
  return Math.round(Math.min(1, Math.max(0, score)) * 100)
}
</script>

<template>
  <details v-if="sources.length" class="mt-3 rounded-xl border border-line bg-shell/70">
    <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
      Источники RAG ({{ sources.length }})
    </summary>
    <div class="space-y-2 px-3 pb-3">
      <div v-if="debug" class="rounded-lg bg-blush/60 px-3 py-2 text-xs text-mocha">
        <div><span class="font-medium">Запрос:</span> {{ debug.original_query }}</div>
        <div>
          <span class="font-medium">После rewrite:</span> {{ debug.rewritten_query }}
          <span v-if="debug.rewrite_fallback"> (fallback)</span>
        </div>
      </div>
      <article
        v-for="source in sources"
        :key="source.chunk_id"
        class="rounded-lg border border-line bg-white px-3 py-2"
      >
        <div class="flex items-center justify-between gap-3">
          <p class="truncate text-sm font-medium">{{ source.title }}</p>
          <span class="shrink-0 rounded-full bg-blush px-2 py-0.5 text-xs text-caramel-dark">
            {{ scorePercent(source.score) }}%
          </span>
        </div>
        <p class="mt-0.5 text-xs text-mocha">{{ source.file }}</p>
        <p class="mt-2 line-clamp-4 text-xs leading-relaxed text-cocoa/80">{{ source.excerpt }}</p>
      </article>
    </div>
  </details>
</template>
