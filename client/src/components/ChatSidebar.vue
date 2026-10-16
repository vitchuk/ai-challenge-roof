<script setup lang="ts">
import type { ChatSummary } from '../types'

defineProps<{ chats: ChatSummary[]; activeId: string | null }>()
const emit = defineEmits<{
  (event: 'select', id: string): void
  (event: 'create'): void
  (event: 'remove', id: string): void
}>()
</script>

<template>
  <aside class="flex w-64 shrink-0 flex-col border-r border-line bg-shell">
    <button
      class="m-3 rounded-xl bg-caramel px-3 py-2 text-sm font-medium text-white transition hover:bg-caramel-dark"
      @click="emit('create')"
    >
      + Новый чат
    </button>
    <ul class="min-h-0 flex-1 overflow-y-auto px-2 pb-3">
      <li v-for="chat in chats" :key="chat.id" class="group mb-1 flex items-center gap-1">
        <button
          class="min-w-0 flex-1 truncate rounded-lg px-3 py-2 text-left text-sm transition"
          :class="chat.id === activeId ? 'bg-blush text-cocoa' : 'text-mocha hover:bg-sand'"
          @click="emit('select', chat.id)"
        >
          {{ chat.title }}
        </button>
        <button
          class="rounded-lg px-2 py-1 text-xs text-mocha opacity-0 transition hover:bg-terracotta/20 hover:text-danger group-hover:opacity-100"
          title="Удалить чат"
          @click="emit('remove', chat.id)"
        >
          ✕
        </button>
      </li>
    </ul>
  </aside>
</template>
