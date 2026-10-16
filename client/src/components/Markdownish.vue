<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{ text: string }>()

interface Block {
  kind: 'quote' | 'text'
  lines: string[]
}

const blocks = computed<Block[]>(() => {
  const result: Block[] = []
  for (const line of props.text.split('\n')) {
    const isQuote = line.trimStart().startsWith('>')
    const kind: Block['kind'] = isQuote ? 'quote' : 'text'
    const clean = isQuote ? line.replace(/^\s*>\s?/, '') : line
    const last = result[result.length - 1]
    if (last && last.kind === kind) {
      last.lines.push(clean)
    } else {
      result.push({ kind, lines: [clean] })
    }
  }
  return result
})
</script>

<template>
  <div class="space-y-2">
    <template v-for="(block, index) in blocks" :key="index">
      <blockquote
        v-if="block.kind === 'quote'"
        class="whitespace-pre-wrap rounded-r-lg border-l-4 border-caramel bg-blush/70 px-3 py-2 italic text-mocha"
      >
        {{ block.lines.join('\n') }}
      </blockquote>
      <p v-else-if="block.lines.join('\n').trim()" class="whitespace-pre-wrap">
        {{ block.lines.join('\n') }}
      </p>
    </template>
  </div>
</template>
