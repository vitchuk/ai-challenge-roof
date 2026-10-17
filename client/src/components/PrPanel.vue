<script setup lang="ts">
import { computed, ref } from 'vue'
import * as api from '../api'
import Markdownish from './Markdownish.vue'
import type { PrCheck, PrDetail, PrReviewBrief, PrSummary } from '../types'

const props = defineProps<{
  prs: PrSummary[] | null
  newCount: number
  secondsLeft: number
  loading: boolean
  error: string
}>()

const emit = defineEmits<{ (event: 'refresh'): void }>()

const selected = ref<number | null>(null)
const detail = ref<PrDetail | null>(null)
const detailLoading = ref(false)
const detailError = ref('')
const rerunning = ref(false)
const rerunNotice = ref('')
const rerunError = ref('')

const diffLines = computed(() => (detail.value ? detail.value.diff.text.split('\n') : []))

const reviewBody = computed(() => {
  const body = detail.value?.review?.body
  if (!body) return ''
  return body
    .split('\n')
    .filter((line) => !line.includes('<!-- ai-review -->'))
    .join('\n')
    .trim()
})

function formatCountdown(total: number): string {
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  if (minutes > 0) return `${minutes}м ${String(seconds).padStart(2, '0')}с`
  return `${seconds}с`
}

function formatDate(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

function fileStatusLetter(status: string): string {
  if (status === 'added') return 'A'
  if (status === 'removed') return 'D'
  if (status === 'renamed') return 'R'
  return 'M'
}

function verdictPill(review: PrReviewBrief | null): { label: string; cls: string } {
  if (!review) return { label: 'нет ревью', cls: 'bg-sand text-mocha' }
  if (review.verdict === 'issues') return { label: 'есть замечания', cls: 'bg-terracotta/20 text-danger' }
  if (review.verdict === 'clean') return { label: 'замечаний нет', cls: 'bg-sage/25 text-cocoa' }
  return { label: 'ревью без вердикта', cls: 'bg-sand text-mocha' }
}

function checkPill(check: PrCheck | null): { label: string; cls: string } {
  if (!check) return { label: 'чек не запускался', cls: 'bg-sand text-mocha' }
  if (check.status !== 'completed') return { label: 'чек выполняется', cls: 'bg-sand text-mocha' }
  if (check.conclusion === 'success') return { label: 'чек пройден', cls: 'bg-sage/25 text-cocoa' }
  if (check.conclusion === 'failure' || check.conclusion === 'timed_out' || check.conclusion === 'startup_failure') {
    return { label: 'чек упал', cls: 'bg-terracotta/20 text-danger' }
  }
  return { label: `чек: ${check.conclusion}`, cls: 'bg-sand text-mocha' }
}

function changeChip(change: string): { label: string; cls: string } {
  if (change === 'new') return { label: 'NEW', cls: 'bg-caramel text-white' }
  if (change === 'push') return { label: 'ОБНОВЛЁН', cls: 'bg-blush text-mocha' }
  return { label: 'РЕВЬЮ', cls: 'bg-blush text-mocha' }
}

function lineClass(line: string): string {
  if (line.startsWith('+++') || line.startsWith('---')) return 'text-mocha'
  if (line.startsWith('@@')) return 'text-caramel-dark'
  if (line.startsWith('+')) return 'bg-sage/25'
  if (line.startsWith('-')) return 'bg-terracotta/15'
  return ''
}

async function loadDetail(number: number, refresh: boolean) {
  detailLoading.value = true
  detailError.value = ''
  rerunNotice.value = ''
  rerunError.value = ''
  try {
    detail.value = await api.getPr(number, refresh)
  } catch (exc) {
    detailError.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    detailLoading.value = false
  }
}

async function selectPr(number: number) {
  selected.value = number
  detail.value = null
  await loadDetail(number, false)
}

async function refreshDetail() {
  if (detail.value) await loadDetail(detail.value.number, true)
}

function back() {
  selected.value = null
  detail.value = null
  detailError.value = ''
}

async function rerun() {
  if (!detail.value || rerunning.value) return
  rerunning.value = true
  rerunNotice.value = ''
  rerunError.value = ''
  try {
    await api.rerunPr(detail.value.number)
    rerunNotice.value = 'Ревью запущено — комментарий появится через несколько минут.'
  } catch (exc) {
    rerunError.value = exc instanceof Error ? exc.message : String(exc)
  } finally {
    rerunning.value = false
  }
}
</script>

<template>
  <details class="rounded-2xl border border-line bg-white" open>
    <summary class="flex cursor-pointer select-none items-center gap-2 px-4 py-3">
      <span class="text-sm font-semibold text-cocoa">Pull Requests</span>
      <span class="rounded-full bg-sand px-2 py-0.5 text-xs font-medium text-mocha">
        {{ prs ? prs.length : '…' }}
      </span>
      <span
        v-if="newCount > 0"
        class="rounded-full bg-caramel px-2 py-0.5 text-xs font-semibold text-white"
      >
        +{{ newCount }}
      </span>
      <span class="ml-auto flex items-center gap-2" @click.stop>
        <span class="text-xs text-mocha">обновление через {{ formatCountdown(secondsLeft) }}</span>
        <button
          class="rounded-lg border border-line bg-shell px-2.5 py-1 text-xs font-medium text-mocha transition hover:text-cocoa disabled:opacity-40"
          :disabled="loading"
          @click="emit('refresh')"
        >
          {{ loading ? 'Обновление…' : 'Обновить' }}
        </button>
      </span>
    </summary>

    <div class="border-t border-line px-4 py-3">
      <p v-if="error" class="rounded-lg bg-terracotta/10 px-3 py-2 text-xs text-danger">{{ error }}</p>

      <template v-else-if="selected === null">
        <p v-if="prs && prs.length === 0" class="text-sm text-mocha">Открытых PR нет.</p>
        <ul v-else class="space-y-2">
          <li v-for="pr in prs" :key="pr.number">
            <button
              class="w-full rounded-xl border border-line bg-shell px-3 py-2 text-left transition hover:border-caramel"
              @click="selectPr(pr.number)"
            >
              <div class="flex items-baseline gap-2">
                <span class="shrink-0 font-mono text-xs text-mocha">#{{ pr.number }}</span>
                <span class="truncate text-sm font-medium text-cocoa">{{ pr.title }}</span>
              </div>
              <div class="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-mocha">
                <span>{{ pr.author }}</span>
                <span>·</span>
                <span class="font-mono">{{ pr.head_branch }} → {{ pr.base_branch }}</span>
                <span>·</span>
                <span>{{ formatDate(pr.updated_at) }}</span>
              </div>
              <div class="mt-1.5 flex flex-wrap items-center gap-1">
                <span
                  v-for="change in pr.changes"
                  :key="change"
                  class="rounded-full px-2 py-0.5 text-[10px] font-semibold"
                  :class="changeChip(change).cls"
                >
                  {{ changeChip(change).label }}
                </span>
                <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="verdictPill(pr.review).cls">
                  {{ verdictPill(pr.review).label }}
                </span>
                <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="checkPill(pr.check).cls">
                  {{ checkPill(pr.check).label }}
                </span>
              </div>
            </button>
          </li>
        </ul>
      </template>

      <template v-else>
        <div class="flex items-center gap-2">
          <button
            class="rounded-lg border border-line bg-shell px-2.5 py-1 text-xs font-medium text-mocha transition hover:text-cocoa"
            @click="back"
          >
            ← К списку
          </button>
          <a
            v-if="detail?.html_url"
            :href="detail.html_url"
            target="_blank"
            rel="noopener"
            class="text-xs text-caramel-dark hover:underline"
          >
            Открыть на GitHub
          </a>
        </div>

        <p v-if="detailLoading && !detail" class="mt-3 text-sm text-mocha">Загрузка PR…</p>
        <p v-else-if="detailError" class="mt-3 rounded-lg bg-terracotta/10 px-3 py-2 text-xs text-danger">
          {{ detailError }}
        </p>

        <template v-else-if="detail">
          <h3 class="mt-3 text-sm font-semibold text-cocoa">
            #{{ detail.number }} {{ detail.title }}
          </h3>
          <p class="mt-1 text-xs text-mocha">
            {{ detail.author }} ·
            <span class="font-mono">{{ detail.head_branch }} → {{ detail.base_branch }}</span> ·
            {{ formatDate(detail.updated_at) }}
            <span v-if="detail.draft" class="ml-1 rounded-full bg-blush px-2 py-0.5 text-[10px] text-mocha">
              черновик
            </span>
          </p>

          <div class="mt-2 flex flex-wrap items-center gap-1.5">
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="checkPill(detail.check).cls">
              {{ checkPill(detail.check).label }}
            </span>
            <span class="rounded-full px-2 py-0.5 text-xs font-medium" :class="verdictPill(detail.review).cls">
              {{ verdictPill(detail.review).label }}
            </span>
          </div>

          <div class="mt-3 flex flex-wrap gap-2">
            <button
              class="rounded-lg border border-line bg-shell px-3 py-1.5 text-xs font-medium text-mocha transition hover:text-cocoa disabled:opacity-40"
              :disabled="detailLoading"
              @click="refreshDetail"
            >
              {{ detailLoading ? 'Обновление…' : 'Обновить' }}
            </button>
            <button
              class="rounded-xl bg-caramel px-4 py-1.5 text-sm font-medium text-white transition hover:bg-caramel-dark disabled:opacity-40"
              :disabled="rerunning"
              @click="rerun"
            >
              {{ rerunning ? 'Запуск…' : 'Перезапустить ревью' }}
            </button>
          </div>

          <p v-if="rerunNotice" class="mt-2 rounded-lg bg-sage/25 px-3 py-2 text-xs text-cocoa">
            {{ rerunNotice }}
          </p>
          <p v-if="rerunError" class="mt-2 rounded-lg bg-terracotta/10 px-3 py-2 text-xs text-danger">
            {{ rerunError }}
          </p>

          <details class="mt-3 rounded-xl border border-line bg-shell/70" open>
            <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
              Изменённые файлы ({{ detail.files.length }})
            </summary>
            <ul class="space-y-1 px-3 pb-3">
              <li
                v-for="file in detail.files"
                :key="file.filename"
                class="flex items-center gap-2 rounded-lg bg-white px-2.5 py-1.5"
              >
                <span class="rounded bg-caramel/25 px-1.5 font-mono text-[10px] text-caramel-dark">
                  {{ fileStatusLetter(file.status) }}
                </span>
                <span class="truncate font-mono text-xs text-cocoa">{{ file.filename }}</span>
                <span class="ml-auto shrink-0 font-mono text-[11px]">
                  <span class="text-cocoa">+{{ file.additions }}</span>
                  <span class="text-danger">−{{ file.deletions }}</span>
                </span>
              </li>
            </ul>
          </details>

          <details class="mt-2 rounded-xl border border-line bg-shell/70">
            <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
              Diff<template v-if="detail.diff.truncated"> (усечён)</template>
            </summary>
            <div class="mx-3 mb-3 max-h-96 overflow-auto rounded-lg bg-cream p-3 font-mono text-[11px] leading-relaxed text-cocoa">
              <span
                v-for="(line, index) in diffLines"
                :key="index"
                class="block whitespace-pre"
                :class="lineClass(line)"
              >{{ line || ' ' }}</span>
            </div>
          </details>

          <details class="mt-2 rounded-xl border border-line bg-shell/70" open>
            <summary class="cursor-pointer select-none px-3 py-2 text-xs font-medium text-mocha">
              AI Review
            </summary>
            <div class="px-3 pb-3">
              <p v-if="!detail.review" class="text-xs text-mocha">
                Ревью пока нет — нажмите «Перезапустить ревью».
              </p>
              <template v-else>
                <p class="text-[11px] text-mocha">обновлено {{ formatDate(detail.review.updated_at) }}</p>
                <div class="mt-2 rounded-lg bg-white px-3 py-2">
                  <Markdownish :text="reviewBody" />
                </div>
              </template>
            </div>
          </details>
        </template>
      </template>
    </div>
  </details>
</template>
