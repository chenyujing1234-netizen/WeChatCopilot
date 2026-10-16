<!-- frontend/components/ReplySuggestionSettings.vue -->
<template>
  <div class="divide-y divide-[var(--app-border-soft)] overflow-hidden rounded-[10px] border border-[var(--app-border)] bg-[var(--app-surface-bg)]">
    <div class="px-3.5 py-3">
      <div class="flex flex-col gap-2.5 sm:flex-row sm:items-center sm:justify-between">
        <div class="min-w-0 flex-1">
          <div class="text-[13px] font-medium text-[var(--app-text-primary)]">回复推荐工作空间</div>
          <div class="mt-0.5 text-[11px] leading-relaxed text-[var(--app-text-muted)]">
            为"推荐回复"提供参考资料：递归读取该目录下的文本文件（txt/md/json/csv/py/js/ts/vue/html/xml/log/yaml/yml/toml/ini/cfg，单文件 100KB、总量 500KB、最多 100 个文件）。
          </div>
        </div>
        <button
          type="button"
          class="shrink-0 rounded-[6px] border px-2.5 py-1.5 text-[12px] transition"
          :class="enabled ? 'border-[var(--app-accent)] bg-[var(--app-surface-muted)] text-[var(--app-accent)]' : 'border-[var(--app-border)] text-[var(--app-text-secondary)] hover:bg-[var(--app-neutral-btn-hover)]'"
          :aria-pressed="enabled"
          @click="toggleEnabled"
        >
          {{ enabled ? '已启用' : '已停用' }}
        </button>
      </div>

      <div class="mt-2.5 flex items-center gap-2">
        <input
          v-model.trim="dir"
          type="text"
          maxlength="1000"
          placeholder="选择或输入工作空间目录的绝对路径"
          class="min-w-0 flex-1 rounded-[6px] border border-[var(--app-border)] bg-[var(--app-surface-bg)] px-2 py-1.5 text-[12px] text-[var(--app-text-primary)] outline-none transition focus:border-[var(--app-accent)]"
          @keydown.enter.prevent="save"
        >
        <button
          type="button"
          class="shrink-0 rounded-[6px] border border-[#e2e2e2] bg-white px-2 py-1.5 text-[12px] text-[#222] transition hover:bg-[#f9f9f9] disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="!canPickDirectory || saving"
          :title="canPickDirectory ? '选择目录' : '当前环境不支持目录选择，请手动输入'"
          @click="chooseDirectory"
        >
          浏览
        </button>
        <button
          type="button"
          class="shrink-0 rounded-[6px] bg-[var(--app-accent)] px-2.5 py-1.5 text-[12px] text-white transition disabled:cursor-not-allowed disabled:opacity-50"
          :disabled="saving || !dirty"
          @click="save"
        >
          {{ saving ? '保存中...' : '保存' }}
        </button>
      </div>

      <p v-if="notice" class="mt-1.5 text-[11px] text-[var(--app-accent)]">{{ notice }}</p>
      <p v-if="error" class="mt-1.5 text-[11px] text-[var(--danger-color)]">{{ error }}</p>
    </div>
  </div>
</template>

<script>
import { defineComponent, computed, onMounted, ref } from 'vue'

export default defineComponent({
  name: 'ReplySuggestionSettings',
  setup() {
    const api = useApi()
    const dir = ref('')
    const enabled = ref(false)
    const savedDir = ref('')
    const savedEnabled = ref(false)
    const saving = ref(false)
    const loading = ref(true)
    const notice = ref('')
    const error = ref('')

    const dirty = computed(() => dir.value !== savedDir.value || enabled.value !== savedEnabled.value)
    const canPickDirectory = computed(() => !!(process.client && window?.wechatDesktop?.chooseDirectory))

    const load = async () => {
      loading.value = true
      error.value = ''
      try {
        const data = await api.getReplySuggestionSettings()
        dir.value = String(data?.workspace_dir || '')
        enabled.value = !!data?.enabled
        savedDir.value = dir.value
        savedEnabled.value = enabled.value
      } catch (err) {
        error.value = String(err?.message || '读取设置失败')
      } finally {
        loading.value = false
      }
    }

    const toggleEnabled = () => { enabled.value = !enabled.value }

    const chooseDirectory = async () => {
      if (!canPickDirectory.value) return
      try {
        const result = await window.wechatDesktop.chooseDirectory({ title: '选择回复推荐工作空间目录' })
        if (result && !result.canceled && Array.isArray(result.filePaths) && result.filePaths.length > 0) {
          dir.value = String(result.filePaths[0] || '').trim()
        }
      } catch {}
    }

    const save = async () => {
      saving.value = true
      notice.value = ''
      error.value = ''
      try {
        const data = await api.updateReplySuggestionSettings({ workspace_dir: dir.value, enabled: enabled.value })
        dir.value = String(data?.workspace_dir ?? dir.value)
        enabled.value = !!data?.enabled
        savedDir.value = dir.value
        savedEnabled.value = enabled.value
        notice.value = '已保存'
        setTimeout(() => { notice.value = '' }, 2000)
      } catch (err) {
        error.value = String(err?.message || '保存失败，请重试')
      } finally {
        saving.value = false
      }
    }

    onMounted(load)

    return { dir, enabled, saving, loading, notice, error, dirty, canPickDirectory, toggleEnabled, chooseDirectory, save }
  }
})
</script>
