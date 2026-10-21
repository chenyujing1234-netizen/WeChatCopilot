<template>
  <div class="min-h-screen px-6 py-10 md:px-10">
    <div class="mx-auto w-full max-w-[980px]">
      <header class="flex items-center gap-4">
        <img src="/logo.png" alt="ContextBuddy Logo" class="h-16 w-16 shrink-0 object-contain" />
        <div>
          <h1 class="text-2xl font-bold text-[#000000e6]">ContextBuddy</h1>
          <p class="mt-1 text-[13px] leading-6 text-[#7F7F7F]">把你的上下文自动保存在本地，需要时随时查看。</p>
        </div>
      </header>

      <div v-if="error" class="mt-6 rounded-[10px] border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-600">
        {{ error }}
      </div>

      <!-- 微信上下文卡片 -->
      <section class="mt-8 rounded-[14px] border border-[#e8e8e8] bg-white p-6 shadow-[0_10px_40px_-24px_rgba(0,0,0,0.35)]">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h2 class="text-[16px] font-semibold text-[#000000e6]">{{ wechatSource?.name || '微信数据' }}</h2>
              <span class="rounded-full px-2 py-0.5 text-[11px] font-medium" :class="stateBadgeClass">{{ stateText }}</span>
            </div>
            <p class="mt-2 text-[13px] leading-6 text-[#7F7F7F]">微信登录后自动保存聊天等数据到本机，并保持实时更新。</p>
          </div>
          <label class="flex shrink-0 cursor-pointer items-center gap-2 text-[12px] text-[#5f5f5f]" title="自动保存总开关">
            <span>自动保存</span>
            <input
              type="checkbox"
              class="h-[18px] w-[18px] accent-[#07c160]"
              :checked="wechatEnabled"
              :disabled="loading || toggling"
              @change="toggleWechatEnabled"
            />
          </label>
        </div>

        <div class="mt-5 grid grid-cols-2 gap-3 rounded-[10px] bg-[#fafafa] px-4 py-3 text-[12px] text-[#5f5f5f] md:grid-cols-3">
          <div>
            <div class="text-[#8a8a8a]">已保存账号</div>
            <div class="mt-1 font-medium text-[#222]">{{ wechatSummary.accounts ?? '—' }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">最近保存</div>
            <div class="mt-1 font-medium text-[#222]">{{ wechatSource?.last_saved_at || '尚未保存' }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">当前账号</div>
            <div class="mt-1 truncate font-medium text-[#222]">{{ wechatSummary.account || '—' }}</div>
          </div>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-[10px] bg-[#fafafa] px-4 py-2.5 text-[12px]">
          <span class="shrink-0 text-[#8a8a8a]">保存位置</span>
          <span class="min-w-0 flex-1 truncate font-medium text-[#222]" :title="dataDirEffective">{{ dataDirEffective || '尚未指定' }}</span>
          <button
            type="button"
            class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="changingDir"
            @click="changeDataDir"
          >
            {{ changingDir ? '正在处理…' : '更改' }}
          </button>
          <button
            v-if="dataDirCustom"
            type="button"
            class="shrink-0 cursor-pointer text-[#8a8a8a] hover:text-[#07c160] disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="changingDir"
            @click="resetDataDir"
          >
            恢复默认
          </button>
        </div>

        <div class="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-[10px] bg-[#fafafa] px-4 py-2.5 text-[12px]">
          <span class="shrink-0 text-[#8a8a8a]" title="每轮自动保存产出的数据类型">归档内容</span>
          <select
            class="shrink-0 cursor-pointer rounded-[6px] border border-[#e4e4e4] bg-white px-2 py-1 font-medium text-[#222] outline-none transition hover:border-[#07c160] disabled:cursor-not-allowed disabled:opacity-60"
            :disabled="changingArchiveContent"
            :value="archiveContent"
            @change="changeArchiveContent"
          >
            <option value="structured">结构化的数据</option>
            <option value="databases">数据库文件</option>
          </select>
          <span class="min-w-0 flex-1 text-[#8a8a8a]">{{ archiveContentHint }}</span>
        </div>

        <div class="mt-5 flex flex-wrap items-center gap-3">
          <button
            type="button"
            class="rounded-[8px] bg-[#07c160] px-4 py-2 text-[13px] font-medium text-white transition hover:bg-[#06ad56] disabled:opacity-60"
            :disabled="syncing"
            @click="syncNow"
          >
            {{ syncing ? '正在保存…' : '立即保存' }}
          </button>
          <button
            type="button"
            class="rounded-[8px] border border-[#e4e4e4] bg-white px-4 py-2 text-[13px] font-medium text-[#333] transition hover:border-[#07c160] hover:text-[#07c160]"
            @click="viewWechatContext"
          >
            查看微信上下文
          </button>
          <div class="ml-auto flex items-center gap-4 text-[12px] text-[#8a8a8a]">
            <a class="cursor-pointer hover:text-[#07c160]" title="导入已有备份" @click="goImport">导入备份</a>
            <a class="cursor-pointer hover:text-[#07c160]" title="检测本机微信数据" @click="goDetection">账号检测</a>
            <a class="cursor-pointer hover:text-[#07c160]" title="导出已保存数据" @click="openExportDialog">导出</a>
          </div>
        </div>
        <p v-if="syncMessage" class="mt-3 text-[12px] leading-5" :class="syncMessageOk ? 'text-[#07964c]' : 'text-red-500'">{{ syncMessage }}</p>
      </section>

      <!-- 规划中的数据源 -->
      <section class="mt-8">
        <h3 class="text-[14px] font-semibold text-[#000000e6]">更多上下文来源（规划中）</h3>
        <div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
          <div
            v-for="source in plannedSources"
            :key="source.source_id"
            class="rounded-[12px] border border-dashed border-[#dcdcdc] bg-white/70 px-5 py-4"
          >
            <div class="flex items-center justify-between gap-3">
              <span class="text-[14px] font-medium text-[#000000e6]">{{ source.name }}</span>
              <span class="rounded-full bg-[#f2f2f2] px-2 py-0.5 text-[11px] text-[#8a8a8a]">规划中</span>
            </div>
            <p class="mt-2 text-[12px] leading-5 text-[#7F7F7F]">{{ source.summary?.description || '即将接入。' }}</p>
          </div>
        </div>
      </section>
    </div>

    <!-- 账号检测浮层：覆盖在主界面上运行检测流程，关闭即回到上下文中心。
         z-[170] 必须低于 GuideDialog 的 z-180，保证面板内的登录/目录提示弹窗盖在浮层之上。 -->
    <div
      v-if="detectionOpen"
      class="fixed inset-0 z-[170] flex items-center justify-center p-3 sm:p-6"
    >
      <div
        class="wechat-detection-overlay-backdrop absolute inset-0 bg-[rgba(14,22,18,0.44)]"
        @click="detectionOpen = false"
      ></div>
      <div
        class="wechat-detection-overlay-card relative max-h-[88vh] w-full max-w-6xl overflow-y-auto rounded-2xl border border-[#DDEBE0] bg-[#F6FCF8] shadow-[0_24px_80px_-24px_rgba(0,0,0,0.45)]"
      >
        <WechatDetectionPanel @close="detectionOpen = false" />
      </div>
    </div>

    <GlobalExportDialog :open="exportDialogOpen" @close="closeExportDialog" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'

const { getContextSources, getContextSettings, updateContextSettings, triggerWechatSync } = useApi()

const sources = ref([])
const wechatEnabled = ref(true)
const loading = ref(true)
const toggling = ref(false)
const syncing = ref(false)
const error = ref('')
const syncMessage = ref('')
const syncMessageOk = ref(true)
const exportDialogOpen = ref(false)

const wechatSource = computed(() => sources.value.find(s => s.source_id === 'wechat') || null)
const plannedSources = computed(() => sources.value.filter(s => s.source_id !== 'wechat'))
const wechatSummary = computed(() => wechatSource.value?.summary || {})

const STATE_TEXT = {
  idle: '待自动保存',
  wechat_detected: '已检测到微信',
  saving: '正在保存',
  up_to_date: '已是最新',
  waiting_wechat: '等待微信登录',
  error: '保存出错，稍后重试',
  disabled: '已暂停'
}

const stateText = computed(() => STATE_TEXT[wechatSource.value?.state || 'idle'] || '待自动保存')

const stateBadgeClass = computed(() => {
  const state = wechatSource.value?.state || 'idle'
  if (state === 'up_to_date') return 'bg-[#eefbf4] text-[#07964c]'
  if (state === 'saving' || state === 'wechat_detected') return 'bg-[#fff7e6] text-[#b7791f]'
  if (state === 'error') return 'bg-[#fdecec] text-[#c53030]'
  return 'bg-[#f2f2f2] text-[#8a8a8a]'
})

const reload = async () => {
  try {
    const [sourcesResp, settingsResp] = await Promise.all([
      getContextSources(),
      getContextSettings()
    ])
    sources.value = sourcesResp?.sources || []
    wechatEnabled.value = !!(settingsResp?.settings?.wechat?.enabled)
  } catch (e) {
    error.value = e?.message || '加载上下文状态失败'
  } finally {
    loading.value = false
  }
}

const toggleWechatEnabled = async (event) => {
  const enabled = !!event?.target?.checked
  toggling.value = true
  wechatEnabled.value = enabled
  try {
    await updateContextSettings({ wechat: { enabled } })
    await reload()
  } catch (e) {
    wechatEnabled.value = !enabled
    error.value = e?.message || '保存开关失败'
  } finally {
    toggling.value = false
  }
}

const syncNow = async () => {
  syncing.value = true
  syncMessageOk.value = true
  syncMessage.value = '正在保存，通常一两分钟内完成，请稍候…'
  try {
    const resp = await triggerWechatSync()
    if (resp?.status === 0) {
      syncMessageOk.value = true
      if (resp?.structured?.ok) {
        syncMessage.value = '本轮保存已完成，结构化的数据已更新。'
      } else if (resp?.structured) {
        syncMessage.value = '本轮保存已完成，结构化的数据未更新，下轮保存会自动重试。'
      } else {
        syncMessage.value = '本轮保存已完成。'
      }
    } else {
      syncMessageOk.value = false
      syncMessage.value = resp?.errmsg || '本轮保存未完成，稍后会自动重试。'
    }
    await reload()
  } catch (e) {
    syncMessageOk.value = false
    syncMessage.value = e?.message || '触发保存失败'
  } finally {
    syncing.value = false
  }
}

// 查看微信上下文以独立子窗口打开（桌面端 window.open → 独立 BrowserWindow），
// 与主界面非模态并存；浏览器开发环境回退为新标签页。
const viewWechatContext = () => { window.open('/chat', '_blank') }

const goImport = async () => { await navigateTo('/import') }

// 保存位置：默认显示应用数据目录，用户可更改；切换时后端会把已保存的数据复制到新位置
const changingDir = ref(false)
const dataDirCustom = computed(() => !!wechatSource.value?.data_dir)
const dataDirEffective = computed(() => wechatSource.value?.data_dir_effective || '')

const applyDataDir = async (dir) => {
  changingDir.value = true
  error.value = ''
  syncMessageOk.value = true
  syncMessage.value = '正在切换保存位置，已保存的数据复制完成后自动生效…'
  try {
    await updateContextSettings({ wechat: { data_dir: dir } })
    await reload()
    syncMessage.value = dir ? '保存位置已更新，已保存的数据已复制到新位置。' : '已恢复默认保存位置。'
  } catch (e) {
    syncMessageOk.value = false
    syncMessage.value = e?.message || '更新保存位置失败'
  } finally {
    changingDir.value = false
  }
}

const changeDataDir = async () => {
  if (changingDir.value) return
  let dir = ''
  if (window?.wechatDesktop?.chooseDirectory) {
    const result = await window.wechatDesktop.chooseDirectory({ title: '选择微信数据保存位置' })
    if (!result || result.canceled || !Array.isArray(result.filePaths) || !result.filePaths.length) return
    dir = String(result.filePaths[0] || '').trim()
  } else {
    dir = String(window.prompt('请输入微信数据保存位置的绝对路径') || '').trim()
  }
  if (!dir) return
  await applyDataDir(dir)
}

const resetDataDir = () => applyDataDir('')

// 归档内容：结构化的数据（默认）或数据库文件，下一轮保存起生效；
// 数据库文件是内部处理必需的数据，两种选择下都会保留在账号目录中
const changingArchiveContent = ref(false)
const archiveContent = computed(() => wechatSource.value?.archive_content || 'structured')
const ARCHIVE_CONTENT_HINTS = {
  structured: '每轮保存后把聊天记录生成为 JSON 与 TXT，数据库文件作为内部数据保留',
  databases: '仅保存数据库文件'
}
const archiveContentHint = computed(() => ARCHIVE_CONTENT_HINTS[archiveContent.value] || ARCHIVE_CONTENT_HINTS.structured)

const changeArchiveContent = async (event) => {
  const value = event?.target?.value || 'structured'
  if (value === archiveContent.value || changingArchiveContent.value) return
  changingArchiveContent.value = true
  try {
    await updateContextSettings({ wechat: { archive_content: value } })
    await reload()
    syncMessageOk.value = true
    syncMessage.value = value === 'structured'
      ? '归档内容已切换为结构化的数据，下一轮保存起生效。'
      : '归档内容已切换为数据库文件，下一轮保存起生效。'
  } catch (e) {
    syncMessageOk.value = false
    syncMessage.value = e?.message || '更新归档内容失败'
    // 失败时把选择框恢复为当前生效值
    if (event?.target) event.target.value = archiveContent.value
  } finally {
    changingArchiveContent.value = false
  }
}

// 账号检测在首页浮层中运行，主界面保持挂载不跳转
const detectionOpen = ref(false)
const goDetection = () => { detectionOpen.value = true }

const openExportDialog = () => { exportDialogOpen.value = true }
const closeExportDialog = () => { exportDialogOpen.value = false }

// 每分钟刷新一次状态：自动保存按小时轮转，页面开着时“最近保存”等也要能看到最新值
let reloadTimer = null
onMounted(() => {
  void reload()
  reloadTimer = setInterval(() => { void reload() }, 60_000)
})
onUnmounted(() => { if (reloadTimer) clearInterval(reloadTimer) })
</script>

<style scoped>
/* 检测浮层卡片暗色主题（背景/描边变量与 GuideDialog 面板一致） */
html[data-theme='dark'] .wechat-detection-overlay-backdrop {
  background: rgba(0, 0, 0, 0.58);
}

html[data-theme='dark'] .wechat-detection-overlay-card {
  border-color: var(--setup-border);
  background: var(--app-surface-bg);
}
</style>
