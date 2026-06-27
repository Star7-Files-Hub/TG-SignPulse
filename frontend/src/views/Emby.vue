<template>
  <div class="flex flex-col gap-3 pb-20">
    <div v-if="loading" class="flex justify-center py-16">
      <Loader2 class="w-5 h-5 animate-spin text-gray-400" />
    </div>
    <template v-else>
      <!-- 标题栏 -->
      <div class="flex items-center justify-between px-1">
        <h1 class="text-base font-semibold text-gray-900 dark:text-gray-100">🎬 Emby 保号</h1>
        <button @click="openAdd" class="text-xs px-3 py-1.5 bg-sky-500 text-white hover:bg-sky-600 rounded transition-colors">+ {{ t('emby.addTask') }}</button>
      </div>

      <!-- 任务列表 -->
      <div v-if="tasks.length === 0" class="flex flex-col items-center justify-center py-16 text-center">
        <p class="text-sm text-gray-500">{{ t('emby.empty') }}</p>
        <p class="text-xs text-gray-400 mt-1">{{ t('emby.emptyHint') }}</p>
      </div>
      <div v-else class="space-y-2">
        <div v-for="task in tasks" :key="task.id" class="border border-gray-200 dark:border-gray-800/60 p-3 rounded">
            <div class="flex items-center justify-between">
              <div class="flex items-center gap-2">
                <span v-if="runningTask === task.id" class="text-[10px] text-sky-500 animate-pulse">⏳</span>
                <span class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ task.name }}</span>
                <span :class="task.enabled ? 'text-emerald-500' : 'text-gray-400'" class="text-[10px]">{{ task.enabled ? '●' : '○' }}</span>
              </div>
            <div class="flex items-center gap-1">
              <button @click="runNow(task)" title="立即执行" class="text-[10px] px-1.5 text-sky-500 hover:text-sky-700">▶</button>
              <button @click="openEdit(task)" class="text-[10px] px-1.5 text-gray-400 hover:text-gray-600">{{ t('common.edit') }}</button>
              <button @click="confirmDelete(task)" class="text-[10px] px-1.5 text-rose-400 hover:text-rose-600">{{ t('common.delete') }}</button>
            </div>
          </div>
          <div class="text-[10px] text-gray-400 mt-1 space-x-3">
            <span>{{ task.accounts?.length || 0 }} {{ t('emby.accounts') }}</span>
            <span>{{ task.watch_minutes }}min</span>
            <span>{{ task.time_range }}</span>
            <span v-if="task.mark_watched" class="text-amber-500">{{ t('emby.markWatched') }}</span>
          </div>
          <div v-if="task.last_run" class="text-[10px] text-gray-400 mt-0.5">{{ t('emby.lastRun') }}: {{ task.last_time_display }} — {{ task.last_result }}</div>
        </div>
      </div>

      <!-- 执行日志 -->
      <section v-if="logs.length > 0" class="pt-4 border-t border-gray-100 dark:border-gray-800/60">
        <h2 class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">📋 {{ t('emby.recentLogs') }}</h2>
        <div class="space-y-0.5 text-[10px] font-mono max-h-48 overflow-y-auto">
          <div v-for="(l, i) in logs" :key="i" class="flex items-center gap-2 p-1 hover:bg-gray-50 dark:hover:bg-gray-800/30">
            <span class="text-gray-400 shrink-0 w-[140px]">{{ formatLogTime(l.time) }}</span>
            <span class="text-gray-600 shrink-0 w-20 truncate">{{ l.task_name }}</span>
            <span class="text-gray-500 shrink-0 w-16 truncate">{{ l.account }}</span>
            <span class="text-gray-500 shrink-0 w-24 truncate">{{ l.item || '-' }}</span>
            <span :class="l.success ? 'text-emerald-500' : 'text-rose-500'" class="shrink-0 w-8">{{ l.success ? '✅' : '❌' }}</span>
            <span v-if="l.error" class="text-rose-400 truncate max-w-[200px]">{{ l.error }}</span>
          </div>
        </div>
      </section>
    </template>

    <!-- Modal -->
    <Modal :isOpen="showModal" :maxWidthClass="'max-w-lg'" @close="showModal = false">
      <template #header>{{ editing ? t('emby.editTitle') : t('emby.addTitle') }}</template>
      <template #body>
        <div class="space-y-3">
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('emby.name') }}</label>
            <input v-model="form.name" :placeholder="t('emby.namePlaceholder')" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
          </div>
          <!-- 账号列表 -->
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500 flex items-center justify-between">
              {{ t('emby.accounts') }} <span class="text-rose-500">*</span>
              <button @click="addAccount" class="text-[10px] text-sky-500 hover:text-sky-700">+ {{ t('emby.addAccount') }}</button>
            </label>
            <div class="space-y-2">
              <div v-for="(acc, i) in form.accounts" :key="i" class="border border-gray-100 dark:border-gray-800/60 p-2 rounded text-xs space-y-1.5">
                <div class="flex justify-between">
                  <span class="text-gray-400">#{{ i + 1 }}</span>
                  <button @click="form.accounts.splice(i, 1)" class="text-rose-400 hover:text-rose-600 text-[10px]">✕</button>
                </div>
                <input v-model="acc.server_url" placeholder="https://emby.example.com" class="w-full h-8 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
                <div class="grid grid-cols-2 gap-2">
                  <input v-model="acc.username" placeholder="用户名" class="w-full h-8 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
                  <input v-model="acc.password" type="password" placeholder="密码" class="w-full h-8 px-2 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
                </div>
              </div>
            </div>
          </div>
          <div class="grid grid-cols-2 gap-2">
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('emby.watchMinutes') }}</label>
              <input v-model.number="form.watch_minutes" type="number" min="5" max="120" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
            </div>
            <div class="space-y-1.5">
              <label class="text-xs font-medium text-gray-500">{{ t('emby.timeRange') }}</label>
              <input v-model="form.time_range" placeholder="08:00-22:00" class="w-full h-10 px-3 text-sm border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400" />
            </div>
          </div>
          <div class="space-y-1.5">
            <label class="text-xs font-medium text-gray-500">{{ t('emby.globalUA') }}</label>
            <select v-model="form.user_agent" class="w-full h-10 px-3 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400">
              <option value="">{{ t('emby.uaRandom') }}</option>
              <option v-for="ua in uaPresets" :key="ua" :value="ua">{{ ua }}</option>
            </select>
            <input v-if="form.user_agent && !uaPresets.includes(form.user_agent)" v-model="form.user_agent" placeholder="自定义 UA" class="w-full h-10 px-3 text-xs border border-gray-200 dark:border-gray-800/60 bg-white dark:bg-gray-900 outline-none focus:border-sky-400 mt-1" />
          </div>
          <label class="flex items-center gap-2 cursor-pointer">
            <input v-model="form.mark_watched" type="checkbox" class="rounded w-3.5 h-3.5" />
            <span class="text-xs text-gray-500">{{ t('emby.markWatched') }}</span>
          </label>
          <p v-if="formError" class="text-xs text-rose-500">{{ formError }}</p>
        </div>
      </template>
      <template #footer>
        <button @click="showModal = false" class="flex-1 py-2 text-sm border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-400 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors">{{ t('common.cancel') }}</button>
        <button @click="save" :disabled="formLoading" class="flex-1 py-2 text-sm bg-gray-900 dark:bg-gray-100 text-white dark:text-gray-950 hover:bg-gray-800 dark:hover:bg-white transition-colors disabled:opacity-50">{{ formLoading ? t('settings.saving') : t('common.save') }}</button>
      </template>
    </Modal>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { Loader2 } from 'lucide-vue-next'
import Modal from '../components/Modal.vue'
import { useI18n } from '../composables/useI18n'
import {
  listEmbyTasks, createEmbyTask, updateEmbyTask, deleteEmbyTask,
  runEmbyTask, getEmbyLogs,
  type EmbyTask,
} from '../lib/api'

const { t, locale } = useI18n()

const uaPresets = [
  'SenPlayer/6.1.2 CFNetwork/1490.0.4 Darwin/23.2.0',
  'Yamby/2.0.3.4(Android)',
  'Hills/0.2.1',
  'Lenna/1.0.15 CFNetwork/1494.0.7 Darwin/23.4.0',
  'VidHub/2.2.4',
]

const tasks = ref<EmbyTask[]>([])
const logs = ref<any[]>([])
const loading = ref(true)
const showModal = ref(false)
const editing = ref<EmbyTask | null>(null)
const formLoading = ref(false)
const formError = ref('')
const form = reactive({
  name: '', accounts: [] as any[], watch_minutes: 30,
  mark_watched: false, time_range: '08:00-22:00',
  user_agent: '',
})

function resetForm(src?: any) {
  form.name = src?.name || ''
  form.accounts = (src?.accounts || []).map((a: any) => ({ server_url: a.server_url || '', username: a.username || '', password: a.password || '' }))
  if (form.accounts.length === 0) form.accounts.push({ server_url: '', username: '', password: '' })
  form.watch_minutes = src?.watch_minutes || 30
  form.mark_watched = src?.mark_watched || false
  form.time_range = src?.time_range || '08:00-22:00'
  form.user_agent = src?.user_agent || ''
}

const openAdd = () => {
  editing.value = null
  resetForm()
  formError.value = ''
  showModal.value = true
}
const openEdit = (t: EmbyTask) => {
  editing.value = t
  resetForm({ ...t, user_agent: (t as any).user_agent || '' })
  formError.value = ''
  showModal.value = true
}
const addAccount = () => form.accounts.push({ server_url: '', username: '', password: '' })

const save = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  formLoading.value = true; formError.value = ''
  try {
    const accounts = form.accounts.map(a => ({
      server_url: a.server_url || '',
      username: a.username || '',
      password: a.password || '',
      user_agent: form.user_agent || '',
    }))
    const data = {
      name: form.name,
      accounts,
      watch_minutes: form.watch_minutes,
      mark_watched: form.mark_watched,
      time_range: form.time_range,
      enabled: true,
    }
    if (editing.value) await updateEmbyTask(token, editing.value.id, data)
    else await createEmbyTask(token, data)
    showModal.value = false
    await refresh()
  } catch (e: any) { formError.value = e.message || '保存失败' }
  formLoading.value = false
}
const confirmDelete = async (t: EmbyTask) => {
  if (!confirm(`删除 "${t.name}"？`)) return
  const token = localStorage.getItem('tg-signer-token') || ''
  await deleteEmbyTask(token, t.id)
  await refresh()
}
const runningTask = ref('')
const runNow = async (t: EmbyTask) => {
  const token = localStorage.getItem('tg-signer-token') || ''
  runningTask.value = t.id
  try {
    await runEmbyTask(token, t.id)
    alert('已提交后台执行，完成后自动更新状态')
  } catch (e: any) {
    alert('提交失败: ' + (e.message || '未知错误'))
    runningTask.value = ''
  }
  await refresh()
  // 每 5 秒轮询直到完成
  const poll = setInterval(async () => {
    try {
      const updated = await listEmbyTasks(token)
      const current = updated.find((u: EmbyTask) => u.id === t.id)
      if (current && !current.last_result?.includes('⏳')) {
        clearInterval(poll)
        runningTask.value = ''
        await refresh()
      }
    } catch { clearInterval(poll); runningTask.value = '' }
  }, 5000)
  setTimeout(() => { clearInterval(poll); runningTask.value = '' }, 120000) // 最多等 2 分钟
}

const formatLogTime = (s: string) => {
  try {
    const d = new Date(s.replace(' ', 'T') + '+00:00')
    return d.toLocaleString(locale.value === 'zh' ? 'zh-CN' : 'en-US', { timeZone: 'Asia/Shanghai', hour12: false })
  } catch { return s }
}

const refresh = async () => {
  const token = localStorage.getItem('tg-signer-token') || ''
  try {
    tasks.value = await listEmbyTasks(token)
    // 格式化时间
    for (const t of tasks.value) {
      (t as any).last_time_display = t.last_run ? formatLogTime(t.last_run) : ''
    }
  } catch { }
  try { logs.value = await getEmbyLogs(token, 50) } catch { }
}

onMounted(async () => {
  await refresh()
  loading.value = false
})
</script>
