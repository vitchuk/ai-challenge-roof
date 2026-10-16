<script setup lang="ts">
import type { CommandInfo } from '../types'

defineProps<{ commands: CommandInfo[]; selected: number }>()
const emit = defineEmits<{ (event: 'select', name: string): void }>()
</script>

<template>
  <ul v-if="commands.length" class="absolute bottom-full left-0 mb-2 w-full overflow-hidden rounded-xl border border-line bg-white shadow-lg">
    <li v-for="(command, index) in commands" :key="command.name">
      <button
        type="button"
        class="flex w-full items-center gap-3 px-3 py-2 text-left transition"
        :class="index === selected ? 'bg-blush' : 'hover:bg-shell'"
        @mousedown.prevent="emit('select', command.name)"
      >
        <span class="rounded-md bg-caramel/20 px-2 py-0.5 font-mono text-sm text-caramel-dark">{{ command.name }}</span>
        <span class="text-xs text-mocha">{{ command.description }}</span>
      </button>
    </li>
  </ul>
</template>
