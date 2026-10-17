<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import * as api from '../api'
import BranchGraph from '../components/BranchGraph.vue'
import ChatSidebar from '../components/ChatSidebar.vue'
import CommandAutocomplete from '../components/CommandAutocomplete.vue'
import Markdownish from '../components/Markdownish.vue'
import PrPanel from '../components/PrPanel.vue'
import RepoTreeView from '../components/RepoTreeView.vue'
import SourcesPanel from '../components/SourcesPanel.vue'
import ToolCallsPanel from '../components/ToolCallsPanel.vue'
import TypingDots from '../components/TypingDots.vue'
import type { ChatSummary, CommandInfo, Message, PrSummary } from '../types'

const props = defineProps<{
  prs: PrSummary[] | null
  newCount: number
  secondsLeft: number
  prLoading: boolean
  prError: string
}>()

const emit = defineEmits<{ (event: 'refresh-prs'): void }>()

const chats = ref<ChatSummary[]>([])
const activeId = ref<string | null>(null)
const messages = ref<Message[]>([])
const input = ref('')
const loading = ref(false)
const error = ref('')
const commands = ref<CommandInfo[]>([])
const selectedCommand = ref(0)
const messagesEl = ref<HTMLElement | null>(null)

const autocompleteCommands = computed(() => {
  const value = input.value
  if (!value.startsWith('/') || value.slice(1).includes(' ')) return []
  return commands.value.filter((command) => command.name.startsWith(value))
})

async function scrollToBottom() {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  }
}

async function loadChats() {
  const data = await api.listChats()
  chats.value = data.chats
  if (!activeId.value && chats.value.length) {
    await selectChat(chats.value[0].id)
  }
}

async function selectChat(id: string) {
  activeId.value = id
  error.value = ''
  const data = await api.getMessages(id)
  messages.value = data.messages
  await scrollToBottom()
}

async function createChat() {
  const chat = await api.createChat()
  chats.value = [chat, ...chats.value]
  activeId.value = chat.id
  messages.value = []
  input.value = ''
}

async function removeChat(id: string) {
  await api.deleteChat(id)
  chats.value = chats.value.filter((chat) => chat.id !== id)
  if (activeId.value === id) {
    activeId.value = null
    messages.value = []
    if (chats.value.length) await selectChat(chats.value[0].id)
    else await createChat()
  }
}

function acceptCommand(name: string) {
  input.value = `${name} `
  selectedCommand.value = 0
}

function onKeydown(event: KeyboardEvent) {
  const options = autocompleteCommands.value
  if (options.length) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      selectedCommand.value = (selectedCommand.value + 1) % options.length
      return
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault()
      selectedCommand.value = (selectedCommand.value - 1 + options.length) % options.length
      return
    }
    if (event.key === 'Tab' || event.key === 'Enter') {
      event.preventDefault()
      acceptCommand(options[selectedCommand.value].name)
      return
    }
  }
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    void send()
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || loading.value || !activeId.value) return
  input.value = ''
  error.value = ''
  const chatId = activeId.value

  const userMessage: Message = {
    id: Date.now(),
    chat_id: chatId,
    role: 'user',
    content: text,
    elapsed_ms: null,
    sources: [],
    debug: null,
    tools: [],
    extra: null,
    created_at: new Date().toISOString(),
  }
  messages.value.push(userMessage)
  loading.value = true
  await scrollToBottom()

  try {
    const response = await api.sendMessage(chatId, text)
    messages.value.push({
      id: response.message_id,
      chat_id: chatId,
      role: 'assistant',
      content: response.reply,
      elapsed_ms: response.elapsed_ms,
      sources: response.sources,
      debug: response.debug,
      tools: response.tools,
      extra: response.extra,
      created_at: new Date().toISOString(),
    })
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    loading.value = false
    await loadChats()
    await scrollToBottom()
  }
}

function elapsed(ms: number | null): string {
  if (ms === null) return ''
  return `${(ms / 1000).toFixed(1)} с`
}

onMounted(async () => {
  try {
    commands.value = (await api.getCommands()).commands
    await loadChats()
    if (!chats.value.length) await createChat()
  } catch (exc) {
    error.value = exc instanceof Error ? exc.message : String(exc)
  }
})
</script>

<template>
  <div class="flex h-full">
    <ChatSidebar
      :chats="chats"
      :active-id="activeId"
      @select="selectChat"
      @create="createChat"
      @remove="removeChat"
    />

    <section class="flex min-w-0 flex-1 flex-col">
      <div class="px-8 pt-4">
        <PrPanel
          :prs="props.prs"
          :new-count="props.newCount"
          :seconds-left="props.secondsLeft"
          :loading="props.prLoading"
          :error="props.prError"
          @refresh="emit('refresh-prs')"
        />
      </div>

      <div ref="messagesEl" class="min-h-0 flex-1 space-y-4 overflow-y-auto px-8 py-6">
        <p v-if="!messages.length && !loading" class="mx-auto max-w-md pt-16 text-center text-sm text-mocha">
          Задайте вопрос по документации проекта командой <span class="font-mono text-caramel-dark">/help</span>.
          Например: <span class="font-mono">/help кратко изложи суть проекта</span>
        </p>

        <div
          v-for="message in messages"
          :key="message.id"
          class="flex"
          :class="message.role === 'user' ? 'justify-end' : 'justify-start'"
        >
          <div
            class="max-w-[80%] rounded-2xl px-4 py-3 text-sm leading-relaxed"
            :class="message.role === 'user' ? 'bg-blush text-cocoa' : 'border border-line bg-white text-cocoa'"
          >
            <p v-if="message.role === 'user'" class="whitespace-pre-wrap">{{ message.content }}</p>
            <template v-else>
              <Markdownish :text="message.content" />
              <RepoTreeView
                v-if="message.extra?.repo_tree"
                :tree="message.extra.repo_tree.tree"
                :files-count="message.extra.repo_tree.files_count"
              />
              <BranchGraph v-if="message.extra?.branch_graph" :graph="message.extra.branch_graph" />
              <SourcesPanel :sources="message.sources" :debug="message.debug" />
              <ToolCallsPanel :tools="message.tools" />
              <p v-if="message.elapsed_ms !== null" class="mt-2 text-xs text-mocha">
                Ответ за {{ elapsed(message.elapsed_ms) }}
              </p>
            </template>
          </div>
        </div>

        <div v-if="loading" class="flex justify-start">
          <div class="rounded-2xl border border-line bg-white px-4 py-3">
            <TypingDots />
          </div>
        </div>

        <p v-if="error" class="mx-auto max-w-lg rounded-xl bg-terracotta/15 px-4 py-2 text-center text-sm text-danger">
          {{ error }}
        </p>
      </div>

      <div class="border-t border-line bg-shell px-8 py-4">
        <div class="relative mx-auto max-w-3xl">
          <CommandAutocomplete
            :commands="autocompleteCommands"
            :selected="selectedCommand"
            @select="acceptCommand"
          />
          <textarea
            v-model="input"
            rows="1"
            class="w-full resize-none rounded-2xl border border-line bg-white px-4 py-3 pr-24 text-sm text-cocoa outline-none transition focus:border-caramel"
            placeholder="Сообщение или /help <вопрос>"
            @keydown="onKeydown"
          />
          <button
            class="absolute bottom-3 right-3 rounded-xl bg-caramel px-4 py-1.5 text-sm font-medium text-white transition hover:bg-caramel-dark disabled:opacity-40"
            :disabled="loading || !input.trim()"
            @click="send"
          >
            Отправить
          </button>
        </div>
      </div>
    </section>
  </div>
</template>
