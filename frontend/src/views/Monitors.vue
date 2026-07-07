<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { Plus, Trash2, Radio, Zap } from 'lucide-vue-next'
import { listMonitors, createMonitor, updateMonitor, deleteMonitor, toggleMonitor, listAccounts } from '../lib/api'
import Modal from '../components/Modal.vue'
import CustomSelect from '../components/CustomSelect.vue'
import MultiSelect from '../components/MultiSelect.vue'
import { useI18n } from '../composables/useI18n'

const { t } = useI18n()
const allMonitors = ref<any[]>([])
const loading = ref(true)
const allAccounts = ref<string[]>([])

// 转发列表（action === 'forward'）
const forwardMonitors = ref<any[]>([])
// 红包列表（action starts with 'red_packet'）
const redPacketMonitors = ref<any[]>([])

const showForwardModal = ref(false)
const showRedPacketModal = ref(false)
const editingMonitor = ref<any>(null)
const formLoading = ref(false)
const formError = ref('')

// 转发表单
const forwardForm = ref({
  id: '', name: '', account_names: [] as string[], keywords: [] as string[],
  match_mode: 'regex', forward_chat_id: null as number | null, dedup_seconds: 60,
  fuzzy_threshold: 0.85, fuzzy_cooldown_minutes: 5,
  smart_dedup: false, forward_with_button: false, smart_dedup_pattern: '', enabled: true,
})
const fwKeywordsText = ref('')
const fwExcludedChatIdsText = ref('')

// 红包表单
const rpForm = ref({
  name: '', account_names: [] as string[], action: 'red_packet_button',
  match_mode: 'regex', extract_pattern: '', grab_text_template: '/grab {number}',
  red_packet_delay: 0, auto_reply_delay: 0, enabled: true,
  exclude_keywords: [] as string[],
})
const rpKeywordsText = ref('')
const rpChatIdsText = ref('')
const rpExcludedChatIdsText = ref('')
const rpButtonNamesText = ref('')
const rpAutoReplyText = ref('')
const rpExcludeKeywordsText = ref('')

const refresh = async () => {
  const token = localStorage.getItem('tg-assistant-token') || ''
  allMonitors.value = await listMonitors(token)
  forwardMonitors.value = allMonitors.value.filter(m => m.action === 'forward')
  redPacketMonitors.value = allMonitors.value.filter(m => m.action.startsWith('red_packet'))
}

// ---- 转发 ----
const openForwardAdd = () => {
  editingMonitor.value = null
  forwardForm.value = { id: '', name: '', account_names: [], forward_targets: [], source_chat_id: null, keywords: [], match_mode: 'regex', forward_chat_id: null, dedup_seconds: 60, fuzzy_threshold: 0.85, fuzzy_cooldown_minutes: 5, smart_dedup: false, forward_with_button: false, smart_dedup_pattern: '', enabled: true }
  fwKeywordsText.value = ''
  fwExcludedChatIdsText.value = ''
  formError.value = ''
  showForwardModal.value = true
}
const openForwardEdit = (m: any) => {
  editingMonitor.value = m
  forwardForm.value = { ...m, dedup_seconds: m.dedup_seconds ?? 60, fuzzy_threshold: m.fuzzy_threshold ?? 0.85, fuzzy_cooldown_minutes: m.fuzzy_cooldown_minutes ?? 5, smart_dedup: m.smart_dedup ?? false, forward_with_button: m.forward_with_button ?? false, smart_dedup_pattern: m.smart_dedup_pattern || '', forward_targets: (m.forward_targets || []).map((t: any) => ({...t})) }
  fwKeywordsText.value = (m.keywords || []).join('\n')
  fwExcludedChatIdsText.value = (m.excluded_chat_ids || []).join('\n')
  formError.value = ''
  showForwardModal.value = true
}
const saveForward = async () => {
  const token = localStorage.getItem('tg-assistant-token') || ''
  formLoading.value = true; formError.value = ''
  try {
    const fwTargets = (forwardForm.value.forward_targets || []).filter((t: any) => t.account && t.forward_chat_id)
    const excludedChatIds = fwExcludedChatIdsText.value.split('\n').map(s => Number(s.trim())).filter(n => n !== 0 && !isNaN(n))
    const data: any = {
      name: forwardForm.value.name,
      action: 'forward',
      keywords: fwKeywordsText.value.split('\n').map(s => s.trim()).filter(Boolean),
      match_mode: forwardForm.value.match_mode,
      forward_targets: fwTargets,
      source_chat_id: forwardForm.value.source_chat_id || null,
      forward_chat_id: fwTargets.length ? null : (forwardForm.value.forward_chat_id || null),
      dedup_seconds: forwardForm.value.dedup_seconds,
      fuzzy_threshold: forwardForm.value.fuzzy_threshold,
      fuzzy_cooldown_minutes: forwardForm.value.fuzzy_cooldown_minutes,
      smart_dedup: forwardForm.value.smart_dedup,
      forward_with_button: forwardForm.value.forward_with_button,
      smart_dedup_pattern: forwardForm.value.smart_dedup_pattern || null,
      excluded_chat_ids: excludedChatIds,
      enabled: forwardForm.value.enabled,
    }
    if (editingMonitor.value) await updateMonitor(token, editingMonitor.value.id, data)
    else await createMonitor(token, data)
    showForwardModal.value = false
    await refresh()
  } catch (e: any) { formError.value = e.message || '保存失败' }
  formLoading.value = false
}

// ---- 红包 ----
const openRedPacketAdd = () => {
  editingMonitor.value = null
  rpForm.value = { name: '', account_names: [], action: 'red_packet_button', match_mode: 'regex', extract_pattern: '', grab_text_template: '/grab {number}', red_packet_delay: 0, auto_reply_delay: 0, enabled: true, exclude_keywords: [] }
  rpKeywordsText.value = ''; rpChatIdsText.value = ''; rpExcludedChatIdsText.value = ''; rpButtonNamesText.value = ''; rpAutoReplyText.value = ''; rpExcludeKeywordsText.value = ''
  formError.value = ''
  showRedPacketModal.value = true
}
const openRedPacketEdit = (m: any) => {
  editingMonitor.value = m
  rpForm.value = { name: m.name || '', account_names: m.account_names || [], action: m.action || 'red_packet_button', match_mode: m.match_mode || 'regex', extract_pattern: m.extract_pattern || '', grab_text_template: m.grab_text_template || '/grab {number}', red_packet_delay: m.red_packet_delay || 0, auto_reply_delay: m.auto_reply_delay || 0, enabled: m.enabled !== false, exclude_keywords: m.exclude_keywords || [] }
  rpKeywordsText.value = (m.keywords || []).join('\n')
  rpChatIdsText.value = (m.chat_ids || []).join('\n')
  rpExcludedChatIdsText.value = (m.excluded_chat_ids || []).join('\n')
  rpButtonNamesText.value = (m.button_names || []).join('\n')
  rpAutoReplyText.value = (m.auto_reply_list || []).join('\n')
  rpExcludeKeywordsText.value = (m.exclude_keywords || []).join('\n')
  formError.value = ''
  showRedPacketModal.value = true
}
const saveRedPacket = async () => {
  const token = localStorage.getItem('tg-assistant-token') || ''
  formLoading.value = true; formError.value = ''
  try {
    const chatIds = rpChatIdsText.value.split('\n').map(s => Number(s.trim())).filter(n => n !== 0 && !isNaN(n))
    const excludedChatIds = rpExcludedChatIdsText.value.split('\n').map(s => Number(s.trim())).filter(n => n !== 0 && !isNaN(n))
    const data: any = {
      name: rpForm.value.name,
      account_names: rpForm.value.account_names,
      action: rpForm.value.action,
      match_mode: rpForm.value.match_mode,
      keywords: rpKeywordsText.value.split('\n').map(s => s.trim()).filter(Boolean),
      chat_ids: chatIds,
      excluded_chat_ids: excludedChatIds,
      button_names: rpButtonNamesText.value.split('\n').map(s => s.trim()).filter(Boolean),
      extract_pattern: rpForm.value.extract_pattern || null,
      grab_text_template: rpForm.value.grab_text_template,
      red_packet_delay: rpForm.value.red_packet_delay || 0,
      auto_reply_list: rpAutoReplyText.value.split('\n').map(s => s.trim()).filter(Boolean),
      auto_reply_delay: rpForm.value.auto_reply_delay || 0,
      exclude_keywords: rpExcludeKeywordsText.value.split('\n').map(s => s.trim()).filter(Boolean),
      enabled: rpForm.value.enabled !== false,
    }
    console.log('[saveRedPacket] chatIds raw:', rpChatIdsText.value, 'parsed:', chatIds, 'data:', JSON.stringify(data))
    if (editingMonitor.value) await updateMonitor(token, editingMonitor.value.id, data)
    else await createMonitor(token, data)
    showRedPacketModal.value = false
    await refresh()
  } catch (e: any) { formError.value = e.message || '保存失败' }
  formLoading.value = false
}

const handleDelete = async (m: any) => {
  if (!confirm(`删除监听器 ${m.name || m.id}？`)) return
  const token = localStorage.getItem('tg-assistant-token') || ''
  await deleteMonitor(token, m.id)
  await refresh()
}

const toggleEnabled = async (m: any) => {
  const token = localStorage.getItem('tg-assistant-token') || ''
  await toggleMonitor(token, m.id)
  await refresh()
}

// ── 实时日志流 (SSE + 轮询双模降级) ──
const sseEvents = ref<any[]>([])
const sseConnected = ref(false)
const sseMode = ref<'sse' | 'polling' | 'offline'>('sse')
const sseCursor = ref(0)
const MAX_SSE_EVENTS = 200
let eventSource: EventSource | null = null
let pollTimer: ReturnType<typeof setInterval> | null = null
let sseFailCount = 0
let sseRetryTimer: ReturnType<typeof setTimeout> | null = null
const SSE_MAX_FAILS = 3
const POLL_INTERVAL_MS = 4000
const SSE_RETRY_INTERVAL_MS = 30000

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const cleanupTimers = () => {
  if (sseRetryTimer) { clearTimeout(sseRetryTimer); sseRetryTimer = null }
  if (eventSource) { eventSource.close(); eventSource = null }
}

// 轮询拉取
const fetchPollLogs = async () => {
  try {
    const token = localStorage.getItem('tg-assistant-token') || ''
    const baseUrl = import.meta.env.VITE_API_BASE || '/api'
    const params = new URLSearchParams({ limit: '30' })
    if (sseCursor.value > 0) params.set('since', String(sseCursor.value))
    const res = await fetch(`${baseUrl}/monitors/logs?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!res.ok) return
    const logs = await res.json()
    if (!Array.isArray(logs) || logs.length === 0) return
    for (const log of logs.slice().reverse()) {
      const ts = new Date(log.time || '').getTime()
      if (ts && ts > sseCursor.value) sseCursor.value = ts
      sseEvents.value.push({
        id: ts || Date.now(),
        time: log.time || '',
        channel: log.event_type || 'info',
        event_type: log.event_type || 'info',
        data: {
          event_type: log.event_type,
          monitor_id: log.monitor_id,
          chat_title: log.chat_title,
          msg_preview: log.msg_preview,
          message: log.message,
        },
      })
    }
    if (sseEvents.value.length > MAX_SSE_EVENTS) {
      sseEvents.value = sseEvents.value.slice(-MAX_SSE_EVENTS)
    }
  } catch { /* ignore */ }
}

const startPolling = () => {
  stopPolling()
  sseMode.value = 'polling'
  sseConnected.value = true  // 轮询也算"已连接"
  pollTimer = setInterval(fetchPollLogs, POLL_INTERVAL_MS)
  fetchPollLogs()
}

const connectSSE = () => {
  const token = localStorage.getItem('tg-assistant-token') || ''
  if (!token) return

  cleanupTimers()
  stopPolling()

  const baseUrl = import.meta.env.VITE_API_BASE || '/api'
  const url = `${baseUrl}/monitors/stream?last_cursor=${sseCursor.value}&channels=monitor_logs,heartbeat,service_status,diagnostic`
  eventSource = new EventSource(url + '&token=' + encodeURIComponent(token))

  eventSource.onopen = () => {
    sseMode.value = 'sse'
    sseConnected.value = true
    sseFailCount = 0
  }

  eventSource.onmessage = (event) => {
    sseFailCount = 0
    try {
      const parsed = JSON.parse(event.data)
      if (parsed.cursor && parsed.cursor > sseCursor.value) sseCursor.value = parsed.cursor
      sseEvents.value.push({
        id: parsed.cursor || Date.now(),
        time: new Date(parsed.timestamp * 1000).toLocaleTimeString(),
        channel: parsed.channel,
        event_type: parsed.data?.event_type || parsed.channel,
        data: parsed.data,
      })
      if (sseEvents.value.length > MAX_SSE_EVENTS) {
        sseEvents.value = sseEvents.value.slice(-MAX_SSE_EVENTS)
      }
    } catch { /* ignore */ }
  }

  eventSource.onerror = () => {
    sseFailCount++
    sseConnected.value = false
    cleanupTimers()

    if (sseFailCount >= SSE_MAX_FAILS) {
      // 降级为轮询，30 秒后重试 SSE
      sseMode.value = 'polling'
      startPolling()
      sseRetryTimer = setTimeout(connectSSE, SSE_RETRY_INTERVAL_MS)
    } else {
      // 指数退避重连（1s, 2s, 4s → 最大 10s）
      const delay = Math.min(1000 * Math.pow(2, sseFailCount - 1), 10000)
      sseRetryTimer = setTimeout(connectSSE, delay)
    }
  }
}

onMounted(async () => {
  // 原有的加载逻辑
  const token = localStorage.getItem('tg-assistant-token') || ''
  try {
    allMonitors.value = await listMonitors(token)
    forwardMonitors.value = allMonitors.value.filter(m => m.action === 'forward')
    redPacketMonitors.value = allMonitors.value.filter(m => m.action.startsWith('red_packet'))
    const res = await listAccounts(token)
    allAccounts.value = (res.accounts || []).map((a: any) => a.name)
  } catch (e) { console.error(e) }
  loading.value = false

  // 连接 SSE 实时日志流
  connectSSE()
})

// 组件卸载时关闭 SSE + 轮询
import { onBeforeUnmount } from 'vue'
onBeforeUnmount(() => {
  cleanupTimers()
  stopPolling()
})

const getEventColor = (eventType: string) => {
  switch (eventType) {
    case 'keyword_match': return 'text-emerald-600'
    case 'forward_success': return 'text-sky-600'
    case 'forward_failure': return 'text-rose-600'
    case 'heartbeat': return 'text-gray-400'
    case 'diagnostic': return 'text-amber-600'
    case 'service_status': return 'text-indigo-600'
    default: return 'text-gray-500'
  }
}

const getEventIcon = (eventType: string) => {
  switch (eventType) {
    case 'keyword_match': return '✅'
    case 'forward_success': return '📨'
    case 'forward_failure': return '❌'
    case 'heartbeat': return '💓'
    case 'diagnostic': return '🔍'
    case 'service_status': return '🔄'
    default: return '📋'
  }
}

const formatEventData = (data: any) => {
  if (!data) return ''
  const parts: string[] = []
  if (data.monitor_id) parts.push(`[${data.monitor_id}]`)
  if (data.account_name) parts.push(`@${data.account_name}`)
  if (data.chat_title) parts.push(data.chat_title)
  if (data.keyword) parts.push(`"${data.keyword}"`)
  if (data.msg_preview) parts.push(data.msg_preview)
  if (data.status) parts.push(`状态: ${data.status}`)
  if (data.message) parts.push(data.message)
  if (data.forward_chat_id) parts.push(`→${data.forward_chat_id}`)
  if (data.error) parts.push(`错误: ${data.error}`)
  return parts.join(' ')
}
</script>

<template>
  <div class="relative min-h-[80vh] space-y-8">
    <div v-if="loading" class="flex justify-center py-20">
      <svg class="animate-spin w-6 h-6 text-gray-400" viewBox="0 0 24 24" fill="none"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
    </div>

    <template v-else>
      <!-- ====== 秒转消息 (主功能) ====== -->
      <section>
        <div class="flex items-center justify-between mb-4">
          <div>
            <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">📨 {{ t('monitors.sectionForward') }}</h2>
            <p class="text-xs text-gray-400 mt-0.5">{{ t('monitors.forwardDesc') }}</p>
          </div>
          <button @click="openForwardAdd" class="flex items-center gap-1 px-3 py-1.5 text-xs bg-sky-600 text-white hover:bg-sky-700 transition-colors"><Plus class="w-3.5 h-3.5" /> {{ t('monitors.addForward') }}</button>
        </div>

        <div v-if="forwardMonitors.length === 0" class="text-center py-12 border border-dashed border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/40">
          <Zap class="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p class="text-sm text-gray-400">{{ t('monitors.noForward') }}</p>
        </div>

        <div v-else class="flex flex-col gap-2">
          <div v-for="m in forwardMonitors" :key="m.id" class="flex items-center gap-3 p-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 hover:border-sky-300 transition-colors">
            <div class="w-7 h-7 bg-sky-50 dark:bg-sky-500/10 border border-sky-100 dark:border-sky-800/30 flex items-center justify-center shrink-0">
              <Zap class="w-3.5 h-3.5 text-sky-500" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-gray-900 dark:text-gray-200 truncate">{{ m.name || 'ID:' + m.id }}</span>
                <span v-if="!m.enabled" class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{{ t('monitors.disabled') }}</span>
              </div>
              <div class="text-xs text-gray-400 mt-0.5">
                <template v-if="m.forward_targets?.length">
                  <span v-for="(t, i) in m.forward_targets" :key="i" class="mr-2">@{{ t.account }} → {{ t.forward_chat_id }}</span>
                </template>
                <template v-else>
                  <span>@{{ (m.account_names || []).join(', ') || '-' }}</span>
                  <span v-if="m.forward_chat_id" class="ml-2">→ {{ m.forward_chat_id }}</span>
                </template>
                <span v-if="(m.excluded_chat_ids || []).length" class="ml-2 text-rose-400">{{ (m.excluded_chat_ids || []).length }} excluded</span>
                <span class="ml-2">{{ (m.keywords || []).slice(0, 3).join(', ') }}{{ (m.keywords || []).length > 3 ? '...' : '' }}</span>
              </div>
            </div>
            <button @click="toggleEnabled(m)" class="p-1.5 text-xs" :class="m.enabled ? 'text-emerald-500' : 'text-gray-300'" :title="m.enabled ? '禁用' : '启用'">{{ m.enabled ? '●' : '○' }}</button>
            <button @click="openForwardEdit(m)" class="p-1.5 text-xs text-gray-400 hover:text-gray-900 dark:hover:text-gray-200">{{ t('common.edit') }}</button>
            <button @click="handleDelete(m)" class="p-1.5 text-gray-400 hover:text-rose-500"><Trash2 class="w-3.5 h-3.5" /></button>
          </div>
        </div>
      </section>

      <!-- ====== 抢红包 (附加功能) ====== -->
      <section>
        <div class="flex items-center justify-between mb-4 pt-6 border-t border-gray-100 dark:border-gray-800/60">
          <div>
            <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">🧧 {{ t('monitors.sectionRedPacket') }}</h2>
            <p class="text-xs text-gray-400 mt-0.5">{{ t('monitors.redPacketDesc') }}</p>
          </div>
          <button @click="openRedPacketAdd" class="flex items-center gap-1 px-3 py-1.5 text-xs bg-rose-600 text-white hover:bg-rose-700 transition-colors"><Plus class="w-3.5 h-3.5" /> {{ t('monitors.addRedPacket') }}</button>
        </div>

        <div v-if="redPacketMonitors.length === 0" class="text-center py-12 border border-dashed border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/40">
          <Radio class="w-8 h-8 text-gray-300 mx-auto mb-2" />
          <p class="text-sm text-gray-400">{{ t('monitors.noRedPacket') }}</p>
        </div>

        <div v-else class="flex flex-col gap-2">
          <div v-for="m in redPacketMonitors" :key="m.id" class="flex items-center gap-3 p-3 bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 hover:border-rose-300 transition-colors">
            <div class="w-7 h-7 bg-rose-50 dark:bg-rose-500/10 border border-rose-100 dark:border-rose-800/30 flex items-center justify-center shrink-0">
              <Radio class="w-3.5 h-3.5 text-rose-500" />
            </div>
            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="text-sm font-medium text-gray-900 dark:text-gray-200 truncate">{{ m.name || 'ID:' + m.id }}</span>
                <span class="text-[10px] px-1.5 py-0.5 rounded" :class="m.action === 'red_packet_button' ? 'bg-amber-50 text-amber-600' : 'bg-purple-50 text-purple-600'">{{ m.action === 'red_packet_button' ? t('monitors.redPacketButton') : t('monitors.redPacketKeyword') }}</span>
                <span v-if="!m.enabled" class="text-[10px] text-gray-400 bg-gray-100 dark:bg-gray-800 px-1.5 py-0.5 rounded">{{ t('monitors.disabled') }}</span>
              </div>
              <div class="text-xs text-gray-400 mt-0.5">
                <span>{{ m.chat_ids?.length || 0 }} chats</span>
                <span v-if="(m.excluded_chat_ids || []).length" class="ml-2 text-rose-400">{{ (m.excluded_chat_ids || []).length }} excluded</span>
                <span class="ml-2">@{{ (m.account_names || []).join(', ') || '-' }}</span>
              </div>
            </div>
            <button @click="toggleEnabled(m)" class="p-2 min-w-[36px] min-h-[36px] flex items-center justify-center text-sm rounded hover:bg-gray-100 dark:hover:bg-gray-800 transition-colors" :class="m.enabled ? 'text-emerald-500' : 'text-gray-300'" :title="m.enabled ? '禁用' : '启用'">{{ m.enabled ? '●' : '○' }}</button>
            <button @click="openRedPacketEdit(m)" class="p-1.5 text-xs text-gray-400 hover:text-gray-900 dark:hover:text-gray-200">{{ t('common.edit') }}</button>
            <button @click="handleDelete(m)" class="p-1.5 text-gray-400 hover:text-rose-500"><Trash2 class="w-3.5 h-3.5" /></button>
          </div>
        </div>
      </section>
    </template>

    <!-- ====== 实时日志流 ====== -->
    <section class="pt-6 border-t border-gray-100 dark:border-gray-800/60">
      <div class="flex items-center justify-between mb-4">
        <div class="flex items-center gap-2">
          <h2 class="text-sm font-semibold text-gray-900 dark:text-gray-100">📡 {{ t('monitors.liveStream') || '实时日志流' }}</h2>
          <span class="w-1.5 h-1.5 rounded-full" :class="sseConnected ? (sseMode === 'sse' ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500') : 'bg-rose-500'"></span>
          <span class="text-[10px]" :class="sseConnected ? (sseMode === 'sse' ? 'text-emerald-500' : 'text-amber-500') : 'text-rose-500'">{{ sseConnected ? (sseMode === 'sse' ? 'SSE' : '轮询') : '断开' }}</span>
        </div>
        <button @click="sseEvents = []" class="text-[10px] text-gray-400 hover:text-gray-600">{{ t('common.clear') || '清空' }}</button>
      </div>

      <div v-if="sseEvents.length === 0" class="text-center py-8 border border-dashed border-gray-200 dark:border-gray-800 bg-gray-50/50 dark:bg-gray-900/40">
        <p class="text-xs text-gray-400">等待实时事件… 关键词命中或转发事件将实时显示在此处。</p>
      </div>

      <div v-else class="border border-gray-200 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden" style="max-height: 420px; overflow-y: auto;">
        <div
          v-for="ev in sseEvents"
          :key="ev.id"
          class="px-3 py-1.5 border-b border-gray-50 dark:border-gray-800/30 last:border-0 hover:bg-gray-50 dark:hover:bg-gray-800/40 transition-colors"
        >
          <div class="flex items-start gap-2 text-[11px]">
            <span class="text-gray-400 shrink-0 w-14 text-right font-mono">{{ ev.time }}</span>
            <span class="shrink-0 w-8 text-right">{{ getEventIcon(ev.event_type) }}</span>
            <span class="truncate" :class="getEventColor(ev.event_type)">{{ formatEventData(ev.data) }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- ====== 转发 Modal ====== -->
    <Modal :isOpen="showForwardModal" @close="showForwardModal = false" :title="editingMonitor ? t('monitors.editForward') : t('monitors.addForward')" maxWidthClass="max-w-lg">
      <div class="space-y-4">
        <div v-if="formError" class="text-xs text-rose-600 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 rounded">{{ formError }}</div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.name') }} <span class="text-rose-500">*</span></label>
          <input v-model="forwardForm.name" :placeholder="t('monitors.namePlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.accounts') }} <span class="text-rose-500">*</span></label>
          <MultiSelect v-model="forwardForm.account_names" :options="allAccounts.map(a => ({label: a, value: a}))" :placeholder="t('monitors.accountsPlaceholder')" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.keywords') }}</label>
          <textarea v-model="fwKeywordsText" rows="3" :placeholder="t('monitors.keywordsPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400 font-mono"></textarea>
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.excludedChatIds') }}</label>
          <textarea v-model="fwExcludedChatIdsText" rows="2" :placeholder="t('monitors.excludedChatIdsPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400"></textarea>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.sourceChatId') }}</label>
            <input v-model.number="forwardForm.source_chat_id" placeholder="留空=全部群聊频道" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.forwardChatId') }} <span class="text-rose-500">*</span></label>
            <input v-model.number="forwardForm.forward_chat_id" placeholder="-10012345678" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
          </div>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.dedupSeconds') }}</label>
            <input v-model.number="forwardForm.dedup_seconds" type="number" min="0" placeholder="60" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
          </div>
        </div>
        <div class="pt-3 border-t border-gray-100 dark:border-gray-800/60">
          <span class="text-[10px] text-gray-400 uppercase tracking-wide mb-2 block">{{ t('monitors.fuzzyDedup') }}</span>
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('monitors.fuzzyThreshold') }}</label>
              <input v-model.number="forwardForm.fuzzy_threshold" type="number" min="0" max="1" step="0.05" placeholder="0.85" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('monitors.fuzzyCooldown') }}</label>
              <input v-model.number="forwardForm.fuzzy_cooldown_minutes" type="number" min="0" placeholder="5" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
            </div>
          </div>
        </div>
        <div class="pt-3 border-t border-gray-100 dark:border-gray-800/60">
          <span class="text-[10px] text-gray-400 uppercase tracking-wide mb-2 block">{{ t('monitors.smartDedup') }}</span>
          <div class="flex items-center gap-3 mb-2">
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" v-model="forwardForm.smart_dedup" class="rounded w-3.5 h-3.5" />
              <span class="text-xs text-gray-500">{{ t('monitors.smartDedupEnable') }}</span>
            </label>
            <label class="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" v-model="forwardForm.forward_with_button" class="rounded w-3.5 h-3.5" />
              <span class="text-xs text-gray-500">{{ t('monitors.forwardWithButton') }}</span>
            </label>
          </div>
          <div v-if="forwardForm.smart_dedup" class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.smartDedupPattern') }}</label>
            <input v-model="forwardForm.smart_dedup_pattern" placeholder="\d+" class="w-full h-10 px-3 text-xs font-mono border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-sky-400" />
          </div>
        </div>
        <p class="text-[10px] text-gray-400 mt-2">{{ t('monitors.forwardNote') }}</p>
      </div>
      <template #footer>
        <button @click="showForwardModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">{{ t('common.cancel') }}</button>
        <button @click="saveForward" :disabled="formLoading" class="px-4 py-2 text-sm bg-sky-600 text-white hover:bg-sky-700 disabled:opacity-50">{{ formLoading ? t('taskModal.saving') : (editingMonitor ? t('taskModal.saveChanges') : t('taskModal.confirmAdd')) }}</button>
      </template>
    </Modal>

    <!-- ====== 红包 Modal ====== -->
    <Modal :isOpen="showRedPacketModal" @close="showRedPacketModal = false" :title="editingMonitor ? t('monitors.editRedPacket') : t('monitors.addRedPacket')" maxWidthClass="max-w-lg">
      <div class="space-y-4">
        <div v-if="formError" class="text-xs text-rose-600 bg-rose-50 dark:bg-rose-500/10 p-2 border border-rose-200 rounded">{{ formError }}</div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.name') }} <span class="text-rose-500">*</span></label>
          <input v-model="rpForm.name" :placeholder="t('monitors.namePlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-rose-400" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.accounts') }} <span class="text-rose-500">*</span></label>
          <MultiSelect v-model="rpForm.account_names" :options="allAccounts.map(a => ({label: a, value: a}))" :placeholder="t('monitors.accountsPlaceholder')" />
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.chatIds') }} <span class="text-rose-500">*</span></label>
          <textarea v-model="rpChatIdsText" rows="2" :placeholder="t('monitors.chatIdsPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-rose-400"></textarea>
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.excludedChatIds') }}</label>
          <textarea v-model="rpExcludedChatIdsText" rows="2" :placeholder="t('monitors.excludedChatIdsPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-rose-400"></textarea>
        </div>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.action') }}</label>
            <CustomSelect v-model="rpForm.action" :options="[
              {label: '🧧 ' + t('monitors.redPacketButton'), value:'red_packet_button'},
              {label: '🧧 ' + t('monitors.redPacketKeyword'), value:'red_packet_keyword'},
            ]" />
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.grabDelay') }}</label>
            <input v-model.number="rpForm.red_packet_delay" type="number" min="0" step="0.1" placeholder="0" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-rose-400" />
          </div>
        </div>
        <template v-if="rpForm.action === 'red_packet_button'">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.buttonNames') }}</label>
            <textarea v-model="rpButtonNamesText" rows="2" :placeholder="t('monitors.buttonNamesPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-rose-400"></textarea>
          </div>
        </template>
        <template v-if="rpForm.action === 'red_packet_keyword'">
          <div class="grid grid-cols-2 gap-4">
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('monitors.extractPattern') }}</label>
              <input v-model="rpForm.extract_pattern" placeholder="\d+" class="w-full h-10 px-3 text-xs font-mono border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-rose-400" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('monitors.grabTemplate') }}</label>
              <input v-model="rpForm.grab_text_template" placeholder="/grab {number}" class="w-full h-10 px-3 text-xs font-mono border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-rose-400" />
            </div>
          </div>
        </template>
        <div class="grid grid-cols-2 gap-4">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.autoReplyList') }}</label>
            <textarea v-model="rpAutoReplyText" rows="2" :placeholder="t('monitors.autoReplyPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-rose-400"></textarea>
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('monitors.replyDelay') }}</label>
            <input v-model.number="rpForm.auto_reply_delay" type="number" min="0" step="0.1" placeholder="0" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 text-gray-900 dark:text-gray-100 outline-none focus:border-rose-400" />
          </div>
        </div>
        <div class="space-y-1.5">
          <label class="text-xs font-medium text-gray-500">{{ t('monitors.excludeKeywords') }}</label>
          <textarea v-model="rpExcludeKeywordsText" rows="2" :placeholder="t('monitors.excludeKeywordsPlaceholder')" class="w-full p-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-rose-400"></textarea>
        </div>
      </div>
      <template #footer>
        <button @click="showRedPacketModal = false" class="px-4 py-2 text-sm text-gray-500 hover:text-gray-900 dark:hover:text-gray-100">{{ t('common.cancel') }}</button>
        <button @click="saveRedPacket" :disabled="formLoading" class="px-4 py-2 text-sm bg-rose-600 text-white hover:bg-rose-700 disabled:opacity-50">{{ formLoading ? t('taskModal.saving') : (editingMonitor ? t('taskModal.saveChanges') : t('taskModal.confirmAdd')) }}</button>
      </template>
    </Modal>
  </div>
</template>
