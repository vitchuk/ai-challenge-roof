<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import * as api from './api'
import ChatView from './views/ChatView.vue'
import SettingsView from './views/SettingsView.vue'
import type { PrSummary } from './types'

type Tab = 'assistant' | 'settings'

const tab = ref<Tab>('assistant')

const tabs: { id: Tab; label: string }[] = [
  { id: 'assistant', label: 'Ассистент' },
  { id: 'settings', label: 'Настройки' },
]

const prs = ref<PrSummary[] | null>(null)
const prError = ref('')
const prLoading = ref(false)
const secondsLeft = ref(0)
const pollInterval = ref(300)
let ticker: number | null = null

const newCount = computed(() => (prs.value ?? []).filter((pr) => pr.changes.length > 0).length)

async function pollPrs(refresh = false) {
  prLoading.value = true
  try {
    const data = await api.getPrs(refresh)
    prs.value = data.prs
    pollInterval.value = data.poll_interval_sec
    prError.value = ''
    secondsLeft.value = pollInterval.value
  } catch (exc) {
    prError.value = exc instanceof Error ? exc.message : String(exc)
    secondsLeft.value = Math.min(pollInterval.value, 60)
  } finally {
    prLoading.value = false
  }
}

function manualRefresh() {
  secondsLeft.value = pollInterval.value
  void pollPrs(true)
}

function startTicker() {
  if (ticker !== null) window.clearInterval(ticker)
  ticker = window.setInterval(() => {
    if (secondsLeft.value > 0) {
      secondsLeft.value -= 1
      if (secondsLeft.value === 0) void pollPrs()
    }
  }, 1000)
}

onMounted(async () => {
  await pollPrs()
  startTicker()
})

onUnmounted(() => {
  if (ticker !== null) window.clearInterval(ticker)
})
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
          class="flex items-center gap-1.5 rounded-full px-4 py-1.5 text-sm font-medium transition"
          :class="tab === item.id ? 'bg-white text-cocoa shadow-sm' : 'text-mocha hover:text-cocoa'"
          @click="tab = item.id"
        >
          {{ item.label }}
          <span
            v-if="item.id === 'assistant' && newCount > 0"
            class="inline-flex items-center rounded-full bg-terracotta px-1.5 py-0.5 text-[10px] font-semibold leading-none text-white"
          >
            {{ newCount }}
          </span>
        </button>
      </nav>
    </header>

    <main class="min-h-0 flex-1">
      <ChatView
        v-if="tab === 'assistant'"
        :prs="prs"
        :new-count="newCount"
        :seconds-left="secondsLeft"
        :pr-loading="prLoading"
        :pr-error="prError"
        @refresh-prs="manualRefresh"
      />
      <SettingsView v-else />
    </main>
  </div>
</template>
