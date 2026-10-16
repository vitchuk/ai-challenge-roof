<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import * as api from '../api'
import BranchGraph from '../components/BranchGraph.vue'
import RepoTreeView from '../components/RepoTreeView.vue'
import type { RepoOverview, Settings, Status } from '../types'

const status = ref<Status | null>(null)
const settings = ref<Settings | null>(null)
const repo = ref<RepoOverview | null>(null)
const repoError = ref('')
const repoLoading = ref(false)
const topK = ref(4)
const saving = ref(false)
const rebuilding = ref(false)
const message = ref('')
let timer: number | undefined

const rag = computed(() => status.value?.rag)
const building = computed(() => rag.value?.build_status === 'building')

async function refresh() {
  try {
    status.value = await api.getStatus()
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  }
}

async function loadRepo(refresh = false) {
  repoLoading.value = true
  repoError.value = ''
  try {
    repo.value = await api.getRepo(refresh)
  } catch (exc) {
    repoError.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    repoLoading.value = false
  }
}

async function loadSettings() {
  settings.value = await api.getSettings()
  topK.value = settings.value.top_k
}

async function saveTopK() {
  if (!settings.value) return
  const min = settings.value.ui.top_k_min
  const max = settings.value.ui.top_k_max
  const value = Math.round(Number(topK.value))
  if (Number.isNaN(value) || value < min || value > max) {
    message.value = `Top_K должен быть в диапазоне ${min}–${max}`
    return
  }
  saving.value = true
  message.value = ''
  try {
    await api.patchSettings({ top_k: value })
    topK.value = value
    message.value = 'Настройки сохранены'
    await loadSettings()
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    saving.value = false
  }
}

async function changeModel(event: Event) {
  const model = (event.target as HTMLSelectElement).value
  try {
    await api.patchSettings({ model })
    await loadSettings()
    message.value = 'Модель обновлена'
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  }
}

async function rebuild() {
  rebuilding.value = true
  message.value = ''
  try {
    await api.rebuildIndex()
    await refresh()
  } catch (exc) {
    message.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    rebuilding.value = false
  }
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString('ru-RU')
}

onMounted(async () => {
  await loadSettings()
  await refresh()
  void loadRepo()
  timer = window.setInterval(refresh, 5000)
})

onUnmounted(() => {
  if (timer) window.clearInterval(timer)
})
</script>

<template>
  <div class="h-full overflow-y-auto px-8 py-6">
    <div class="mx-auto max-w-3xl space-y-5">
      <p v-if="message" class="rounded-xl bg-blush px-4 py-2 text-sm text-cocoa">{{ message }}</p>

      <section class="rounded-2xl border border-line bg-white p-5">
        <div class="mb-3 flex items-center justify-between">
          <h2 class="text-base font-semibold">RAG-база данных</h2>
          <span
            class="rounded-full px-3 py-1 text-xs font-medium"
            :class="rag?.exists ? 'bg-sage/25 text-cocoa' : 'bg-terracotta/20 text-danger'"
          >
            {{ building ? 'Индексация…' : rag?.exists ? 'Индекс построен' : 'Индекс не построен' }}
          </span>
        </div>
        <dl class="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
          <div class="flex justify-between"><dt class="text-mocha">Фрагментов</dt><dd>{{ rag?.chunks ?? 0 }}</dd></div>
          <div class="flex justify-between"><dt class="text-mocha">Файлов</dt><dd>{{ rag?.files ?? 0 }}</dd></div>
          <div class="flex justify-between"><dt class="text-mocha">Модель эмбеддингов</dt><dd>{{ rag?.embedding_model ?? '—' }}</dd></div>
          <div class="flex justify-between"><dt class="text-mocha">Размерность</dt><dd>{{ rag?.dim ?? '—' }}</dd></div>
          <div class="col-span-2 flex justify-between"><dt class="text-mocha">Построен</dt><dd>{{ formatDate(rag?.built_at) }}</dd></div>
        </dl>
        <p v-if="rag?.error" class="mt-3 rounded-lg bg-terracotta/10 px-3 py-2 text-xs text-danger">{{ rag.error }}</p>
        <div class="mt-4 rounded-xl bg-shell p-4 text-xs leading-relaxed text-mocha">
          <p class="mb-1 font-medium text-cocoa">Принцип индексации (стратегия fixed)</p>
          <p>
            Документы проекта читаются через GitHub MCP и режутся скользящим окном по предложениям:
            целевой размер {{ settings?.rag_params.min_tokens ?? 500 }}–{{ settings?.rag_params.max_tokens ?? 1000 }} токенов,
            перекрытие {{ settings?.rag_params.overlap_tokens ?? 150 }},
            оценка {{ settings?.rag_params.chars_per_token ?? 3 }} символа/токен.
            Каждый фрагмент снабжается именем файла и заголовком, затем отправляется в локальную модель
            <span class="font-mono">{{ rag?.embedding_model ?? 'qwen3-embedding:0.6b' }}</span> (Ollama),
            векторы нормализуются и сохраняются в локальный JSON-индекс.
          </p>
        </div>
        <button
          class="mt-4 rounded-xl bg-caramel px-4 py-2 text-sm font-medium text-white transition hover:bg-caramel-dark disabled:opacity-40"
          :disabled="building || rebuilding || !status?.mcp.connected"
          @click="rebuild"
        >
          Переиндексировать
        </button>
      </section>

      <section class="rounded-2xl border border-line bg-white p-5">
        <h2 class="mb-3 text-base font-semibold">Стратегия поиска</h2>
        <p class="rounded-xl bg-shell p-4 text-xs leading-relaxed text-mocha">
          <span class="font-medium text-cocoa">Query Rewrite:</span>
          вопрос пользователя переписывается моделью DeepSeek в самодостаточный поисковый запрос
          (с учётом истории диалога), затем выполняется поиск по косинусной близости, берутся
          Top_K фрагментов и только они передаются модели для ответа. При ошибке переписывания
          используется исходный вопрос.
        </p>
        <div class="mt-4 flex items-center gap-3">
          <label class="text-sm text-mocha">Top_K</label>
          <input
            v-model.number="topK"
            type="number"
            :min="settings?.ui.top_k_min ?? 1"
            :max="settings?.ui.top_k_max ?? 10"
            class="w-20 rounded-lg border border-line bg-cream px-3 py-1.5 text-sm outline-none focus:border-caramel"
          />
          <button
            class="rounded-lg bg-caramel px-3 py-1.5 text-sm font-medium text-white transition hover:bg-caramel-dark disabled:opacity-40"
            :disabled="saving"
            @click="saveTopK"
          >
            Сохранить
          </button>
          <span class="text-xs text-mocha">по умолчанию 4, применяется сразу</span>
        </div>
      </section>

      <section class="rounded-2xl border border-line bg-white p-5">
        <h2 class="mb-3 text-base font-semibold">Подключения</h2>
        <ul class="space-y-3 text-sm">
          <li class="flex items-center justify-between gap-4 rounded-xl bg-shell px-4 py-3">
            <div>
              <p class="font-medium">Ollama</p>
              <p class="text-xs text-mocha">{{ status?.ollama.base_url }} · {{ status?.ollama.model }}</p>
            </div>
            <span class="rounded-full px-3 py-1 text-xs font-medium" :class="status?.ollama.connected && status?.ollama.model_present ? 'bg-sage/25 text-cocoa' : 'bg-terracotta/20 text-danger'">
              {{ status?.ollama.connected ? (status?.ollama.model_present ? 'подключено' : 'нет модели') : 'нет связи' }}
            </span>
          </li>
          <li class="flex items-center justify-between gap-4 rounded-xl bg-shell px-4 py-3">
            <div>
              <p class="font-medium">DeepSeek</p>
              <div class="mt-1 flex items-center gap-2">
                <select
                  v-if="settings"
                  class="rounded-lg border border-line bg-white px-2 py-1 text-xs outline-none focus:border-caramel"
                  :value="settings.model"
                  @change="changeModel"
                >
                  <option v-for="model in settings.allowed_models" :key="model" :value="model">{{ model }}</option>
                </select>
              </div>
            </div>
            <span class="rounded-full px-3 py-1 text-xs font-medium" :class="status?.deepseek.configured ? 'bg-sage/25 text-cocoa' : 'bg-terracotta/20 text-danger'">
              {{ status?.deepseek.configured ? 'ключ задан' : 'нет ключа' }}
            </span>
          </li>
          <li class="rounded-xl bg-shell px-4 py-3">
            <div class="flex items-center justify-between gap-4">
              <div>
                <p class="font-medium">MCP GitHub</p>
                <p class="text-xs text-mocha">
                  {{ status?.github.owner }}/{{ status?.github.repo }} ({{ status?.github.branch }}) ·
                  инструментов: {{ status?.mcp.tools_count ?? 0 }}
                </p>
              </div>
              <span class="rounded-full px-3 py-1 text-xs font-medium" :class="status?.mcp.connected ? 'bg-sage/25 text-cocoa' : 'bg-terracotta/20 text-danger'">
                {{ status?.mcp.connected ? 'подключено' : 'нет связи' }}
              </span>
            </div>
            <p v-if="status?.mcp.error" class="mt-2 text-xs text-danger">{{ status.mcp.error }}</p>
            <p v-if="status?.mcp.tools?.length" class="mt-2 font-mono text-[11px] leading-relaxed text-mocha">
              {{ status.mcp.tools.join(', ') }}
            </p>
          </li>
        </ul>
      </section>

      <section class="rounded-2xl border border-line bg-white p-5">
        <div class="mb-3 flex items-center justify-between gap-4">
          <div class="flex items-center gap-3">
            <h2 class="text-base font-semibold">Репозиторий</h2>
            <span
              v-if="repo"
              class="rounded-full bg-caramel px-3 py-1 text-xs font-medium text-white"
            >
              ветка: {{ repo.current_branch }}
            </span>
          </div>
          <button
            class="rounded-lg bg-caramel px-3 py-1.5 text-sm font-medium text-white transition hover:bg-caramel-dark disabled:opacity-40"
            :disabled="repoLoading || !status?.mcp.connected"
            @click="loadRepo(true)"
          >
            {{ repoLoading ? 'Загрузка…' : 'Обновить' }}
          </button>
        </div>
        <p v-if="repoError" class="rounded-lg bg-terracotta/10 px-3 py-2 text-xs text-danger">
          {{ repoError }}
        </p>
        <template v-if="repo">
          <p class="mb-3 text-xs text-mocha">Файлов в дереве: {{ repo.files_count }}</p>
          <div class="flex flex-wrap gap-2">
            <span
              v-for="branch in repo.branches"
              :key="branch.name"
              class="rounded-full px-2 py-0.5 text-xs"
              :class="branch.current ? 'bg-caramel text-white' : 'bg-blush text-mocha'"
            >
              {{ branch.name }} · {{ branch.commits }}
            </span>
          </div>
          <BranchGraph :graph="repo" class="mt-3" />
          <RepoTreeView :tree="repo.tree" :files-count="repo.files_count" />
        </template>
        <p v-else-if="repoLoading" class="text-xs text-mocha">Загружаю ветки и дерево файлов через MCP…</p>
      </section>
    </div>
  </div>
</template>
