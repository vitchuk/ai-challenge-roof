<script setup lang="ts">
import type { ToolCallEvent } from '../types'

defineProps<{ tools: ToolCallEvent[] }>()

function formatArguments(args: Record<string, unknown>): string {
  const entries = Object.entries(args)
  if (!entries.length) return '—'
  return entries.map(([key, value]) => `${key}: ${JSON.stringify(value)}`).join(', ')
}
</script>

<template>
  <details v-if="tools.length" class="mt-3 rounded-xl border border-line bg-shell/70">
    <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
      Вызовы MCP ({{ tools.length }})
    </summary>
    <ul class="space-y-2 px-3 pb-3">
      <li
        v-for="(tool, index) in tools"
        :key="index"
        class="rounded-lg border border-line bg-white px-3 py-2"
      >
        <div class="flex items-center gap-2">
          <span class="rounded-md bg-caramel/25 px-2 py-0.5 font-mono text-xs text-caramel-dark">
            {{ tool.name }}
          </span>
          <span v-if="tool.is_error" class="text-xs text-danger">ошибка</span>
        </div>
        <p class="mt-1 break-words font-mono text-[11px] text-mocha">
          {{ formatArguments(tool.arguments) }}
        </p>
        <pre class="mt-2 max-h-40 overflow-auto whitespace-pre-wrap break-words rounded-md bg-cream px-2 py-1 text-[11px] text-cocoa/80">{{ tool.preview }}</pre>
      </li>
    </ul>
  </details>
</template>
