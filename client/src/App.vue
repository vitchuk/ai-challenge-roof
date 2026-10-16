<script setup lang="ts">
import { ref } from 'vue'
import ChatView from './views/ChatView.vue'
import SettingsView from './views/SettingsView.vue'

type Tab = 'assistant' | 'settings'

const tab = ref<Tab>('assistant')

const tabs: { id: Tab; label: string }[] = [
  { id: 'assistant', label: 'Ассистент' },
  { id: 'settings', label: 'Настройки' },
]
</script>

<template>
  <div class="flex h-full flex-col bg-cream">
    <header class="flex items-center gap-6 border-b border-line bg-shell px-6 py-3">
      <div class="flex items-center gap-2">
        <span class="grid h-8 w-8 place-items-center rounded-full bg-caramel text-base font-semibold text-white">AI</span>
        <div>
          <h1 class="text-base font-semibold leading-tight">AI Challenge Roof</h1>
          <p class="text-xs text-mocha">RAG-ассистент по документации проекта</p>
        </div>
      </div>
      <nav class="flex gap-1 rounded-full bg-sand p-1">
        <button
          v-for="item in tabs"
          :key="item.id"
          class="rounded-full px-4 py-1.5 text-sm font-medium transition"
          :class="tab === item.id ? 'bg-white text-cocoa shadow-sm' : 'text-mocha hover:text-cocoa'"
          @click="tab = item.id"
        >
          {{ item.label }}
        </button>
      </nav>
    </header>

    <main class="min-h-0 flex-1">
      <ChatView v-if="tab === 'assistant'" />
      <SettingsView v-else />
    </main>
  </div>
</template>
