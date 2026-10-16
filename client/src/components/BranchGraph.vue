<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import type { BranchGraph } from '../types'

const props = defineProps<{ graph: BranchGraph }>()
const container = ref<HTMLElement | null>(null)
const error = ref('')

let mermaidPromise: Promise<typeof import('mermaid').default> | null = null

function getMermaid() {
  if (!mermaidPromise) {
    mermaidPromise = import('mermaid').then(({ default: mermaid }) => {
      mermaid.initialize({
        startOnLoad: false,
        securityLevel: 'strict',
        theme: 'base',
        themeVariables: {
          primaryColor: '#F1DDC6',
          primaryTextColor: '#4A3F35',
          primaryBorderColor: '#D9A066',
          lineColor: '#C4884B',
          secondaryColor: '#E6D8C0',
          tertiaryColor: '#FBF7F0',
          fontFamily: 'Segoe UI, system-ui, sans-serif',
        },
      })
      return mermaid
    })
  }
  return mermaidPromise
}

async function render() {
  if (!container.value || !props.graph.mermaid) return
  error.value = ''
  const id = `gitgraph-${Math.random().toString(36).slice(2)}`
  try {
    const mermaid = await getMermaid()
    const { svg } = await mermaid.render(id, props.graph.mermaid)
    if (container.value) container.value.innerHTML = svg
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  }
}

onMounted(render)
watch(() => props.graph.mermaid, render)
</script>

<template>
  <details class="mt-3 rounded-xl border border-line bg-shell/70" open>
    <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
      Ветки репозитория ({{ graph.branches.length }}) · текущая: {{ graph.current_branch }}
    </summary>
    <div class="px-3 pb-3">
      <div class="mb-2 flex flex-wrap gap-2">
        <span
          v-for="branch in graph.branches"
          :key="branch.name"
          class="rounded-full px-2 py-0.5 text-xs"
          :class="branch.current ? 'bg-caramel text-white' : 'bg-blush text-mocha'"
        >
          {{ branch.name }} · {{ branch.commits }}
        </span>
      </div>
      <div v-if="graph.mermaid" ref="container" class="overflow-auto rounded-lg bg-white p-2" />
      <p v-else class="rounded-lg bg-white px-2 py-1 text-xs text-mocha">
        Нет коммитов для построения графа.
      </p>
      <p v-if="error" class="mt-1 text-xs text-danger">{{ error }}</p>
    </div>
  </details>
</template>
