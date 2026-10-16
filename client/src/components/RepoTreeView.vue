<script setup lang="ts">
import { ref, watch } from 'vue'
import { TreeView } from '@grapoza/vue-tree'
import type { RepoTreeNode } from '../types'

const props = defineProps<{ tree: RepoTreeNode[]; filesCount?: number }>()

interface TreeModel {
  id: string
  label: string
  children?: TreeModel[]
}

function toModel(nodes: RepoTreeNode[]): TreeModel[] {
  return nodes.map((node) => ({
    id: node.path,
    label: node.type === 'dir' ? `${node.name}/` : node.name,
    children: node.children.length ? toModel(node.children) : undefined,
  }))
}

const model = ref<TreeModel[]>(toModel(props.tree))
watch(
  () => props.tree,
  (value) => {
    model.value = toModel(value)
  },
)
</script>

<template>
  <details class="mt-3 rounded-xl border border-line bg-shell/70" open>
    <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
      Дерево файлов репозитория ({{ filesCount ?? 0 }})
    </summary>
    <div class="max-h-96 overflow-auto px-3 pb-3 text-sm">
      <TreeView v-model="model" />
    </div>
  </details>
</template>
