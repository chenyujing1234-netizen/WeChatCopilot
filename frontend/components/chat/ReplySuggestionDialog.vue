<!-- frontend/components/chat/ReplySuggestionDialog.vue -->
<template>
  <Teleport to="body">
    <div class="rsd-overlay" @click.self="$emit('close')">
      <section class="rsd-panel" role="dialog" aria-modal="true" aria-label="推荐回复">
        <header class="rsd-header">
          <div class="min-w-0">
            <h3>推荐回复</h3>
            <p class="rsd-muted">{{ headerHint }}</p>
          </div>
          <button type="button" class="rsd-icon-btn" aria-label="关闭" @click="$emit('close')">✕</button>
        </header>

        <div v-if="loading" class="rsd-body rsd-centered">
          <span class="rsd-spin" aria-hidden="true"></span> 正在结合聊天上下文{{ workspaceLabel }}生成建议...
        </div>

        <div v-else-if="error" class="rsd-body rsd-centered rsd-error" role="alert">
          <p>{{ error }}</p>
          <div class="rsd-actions">
            <button v-if="errorCode === 'ai_not_configured'" type="button" class="rsd-primary" @click="openSettings">去设置 AI 服务</button>
            <button v-else type="button" class="rsd-primary" @click="generate">重试</button>
            <button type="button" class="rsd-ghost" @click="$emit('close')">关闭</button>
          </div>
        </div>

        <template v-else>
          <div class="rsd-body">
            <div class="rsd-target">
              <div class="rsd-target-meta">{{ message?.sender }} · {{ message?.fullTime }}</div>
              <div class="rsd-target-text">{{ targetText }}</div>
            </div>
            <label class="rsd-extra">
              <span>补充要求（可选）</span>
              <input v-model="extraInstruction" type="text" maxlength="2000" placeholder="例如：语气轻松一点，确认时间地点" @keydown.enter.prevent="generate" />
            </label>
            <div class="rsd-suggestion">{{ suggestion }}</div>
            <details v-if="result" class="rsd-details">
              <summary>参考信息（{{ result.contextMessages }} 条上下文<template v-if="result.filesConsidered?.length">，{{ result.filesConsidered.length }} 个文件</template>）</summary>
              <p v-if="!result.workspaceUsed && workspaceRequested" class="rsd-warn">工作空间未生效：目录不存在或没有可读取的文本文件。</p>
              <p v-else-if="!result.workspaceUsed">未参考工作空间（可在设置中启用）。</p>
              <p v-if="result.workspaceTruncated" class="rsd-warn">工作空间内容超出上限，已截断。</p>
              <ul v-if="result.filesConsidered?.length" class="rsd-files">
                <li v-for="name in result.filesConsidered" :key="name">{{ name }}</li>
              </ul>
              <p class="rsd-muted">模型：{{ result.model }} · 耗时 {{ result.elapsedMs }}ms</p>
            </details>
          </div>
          <footer class="rsd-footer">
            <button type="button" class="rsd-primary" :disabled="loading" @click="generate">重新生成</button>
            <button type="button" class="rsd-ghost" :disabled="!suggestion || copied" @click="copy">{{ copied ? '已复制' : '复制' }}</button>
            <button type="button" class="rsd-ghost" @click="$emit('close')">关闭</button>
          </footer>
        </template>
      </section>
    </div>
  </Teleport>
</template>

<script>
import { defineComponent, ref, computed, watch } from 'vue'

export default defineComponent({
  name: 'ReplySuggestionDialog',
  props: {
    account: { type: String, default: '' },
    contact: { type: Object, default: null },
    message: { type: Object, default: null }
  },
  emits: ['close'],
  setup(props) {
    const api = useApi()
    const settingsDialog = useSettingsDialog()
    const loading = ref(false)
    const error = ref('')
    const errorCode = ref('')
    const suggestion = ref('')
    const result = ref(null)
    const extraInstruction = ref('')
    const copied = ref(false)
    const workspaceDir = ref('')

    const targetText = computed(() => String(props.message?.content || '').slice(0, 120))
    const headerHint = computed(() => {
      const name = props.contact?.name || props.contact?.username || ''
      return name ? `会话：${name}` : ''
    })
    const workspaceRequested = computed(() => !!workspaceDir.value)
    const workspaceLabel = computed(() => (workspaceRequested.value ? '与工作空间' : ''))

    const generate = async () => {
      const anchorId = String(props.message?.id || '').trim()
      if (!anchorId) return
      loading.value = true
      error.value = ''
      errorCode.value = ''
      suggestion.value = ''
      result.value = null
      copied.value = false
      try {
        let settings = null
        try {
          settings = await api.getReplySuggestionSettings()
        } catch {}
        workspaceDir.value = String(settings?.workspace_dir || '').trim()
        const data = await api.generateReplySuggestion({
          account: props.account,
          conversation: props.contact?.username || '',
          anchor_id: anchorId,
          extra_instruction: extraInstruction.value.trim()
        })
        suggestion.value = String(data?.suggestion || '').trim()
        result.value = data
        if (!suggestion.value) {
          error.value = '模型未返回建议，请重试。'
        }
      } catch (err) {
        error.value = String(err?.message || '生成失败，请重试')
        errorCode.value = String(err?.code || '')
      } finally {
        loading.value = false
      }
    }

    const copy = async () => {
      try {
        await navigator.clipboard.writeText(suggestion.value)
        copied.value = true
        setTimeout(() => { copied.value = false }, 2000)
      } catch {}
    }

    const openSettings = () => {
      settingsDialog.openDialog()
    }

    watch(() => props.message, () => {
      if (props.message) generate()
    }, { immediate: true })

    return {
      loading, error, errorCode, suggestion, result, extraInstruction, copied,
      workspaceDir, workspaceRequested, workspaceLabel, targetText, headerHint,
      generate, copy, openSettings
    }
  }
})
</script>

<style scoped>
.rsd-overlay { position: fixed; inset: 0; z-index: 90; display: flex; align-items: center; justify-content: center; background: rgba(0,0,0,.45); padding: 16px; }
.rsd-panel { width: 520px; max-width: 100%; max-height: 86vh; display: flex; flex-direction: column; border-radius: 12px; background: var(--app-surface-bg, #fff); box-shadow: 0 20px 50px rgba(0,0,0,.25); overflow: hidden; }
.rsd-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; padding: 14px 16px 10px; border-bottom: 1px solid var(--app-border-soft, #eee); }
.rsd-header h3 { margin: 0; font-size: 15px; color: var(--app-text-primary, #222); }
.rsd-muted { margin: 2px 0 0; font-size: 11px; color: var(--app-text-muted, #999); }
.rsd-body { padding: 14px 16px; overflow-y: auto; display: flex; flex-direction: column; gap: 10px; }
.rsd-centered { align-items: center; justify-content: center; min-height: 140px; text-align: center; color: var(--app-text-secondary, #666); font-size: 13px; }
.rsd-error { color: var(--danger-color, #dc2626); }
.rsd-actions { display: flex; gap: 8px; justify-content: center; }
.rsd-target { border-left: 3px solid var(--app-accent, #07b75b); padding: 6px 10px; background: var(--app-surface-soft, #f7f7f7); border-radius: 6px; }
.rsd-target-meta { font-size: 11px; color: var(--app-text-muted, #999); margin-bottom: 2px; }
.rsd-target-text { font-size: 12px; color: var(--app-text-primary, #333); word-break: break-all; }
.rsd-extra { display: flex; flex-direction: column; gap: 4px; font-size: 11px; color: var(--app-text-muted, #888); }
.rsd-extra input { border: 1px solid var(--app-border, #e2e2e2); border-radius: 6px; padding: 6px 8px; font-size: 12px; background: var(--app-surface-bg, #fff); color: var(--app-text-primary, #333); outline: none; }
.rsd-extra input:focus { border-color: var(--app-accent, #07b75b); }
.rsd-suggestion { white-space: pre-wrap; font-size: 13px; line-height: 1.7; color: var(--app-text-primary, #222); background: var(--app-surface-soft, #f7f7f7); border-radius: 8px; padding: 12px; }
.rsd-details { font-size: 11px; color: var(--app-text-secondary, #666); }
.rsd-details summary { cursor: pointer; user-select: none; }
.rsd-files { margin: 6px 0 0; padding-left: 18px; max-height: 120px; overflow-y: auto; }
.rsd-warn { color: var(--danger-color, #dc2626); margin: 4px 0 0; }
.rsd-footer { display: flex; gap: 8px; justify-content: flex-end; padding: 12px 16px; border-top: 1px solid var(--app-border-soft, #eee); }
.rsd-primary, .rsd-ghost, .rsd-icon-btn { border-radius: 6px; font-size: 12px; cursor: pointer; transition: all .15s; }
.rsd-primary { background: var(--app-accent, #07b75b); color: #fff; border: none; padding: 6px 14px; }
.rsd-primary:hover { filter: brightness(1.05); }
.rsd-primary:disabled, .rsd-ghost:disabled { opacity: .5; cursor: not-allowed; }
.rsd-ghost { background: transparent; color: var(--app-text-secondary, #555); border: 1px solid var(--app-border, #e2e2e2); padding: 6px 14px; }
.rsd-ghost:hover { background: var(--app-surface-soft, #f7f7f7); }
.rsd-icon-btn { background: transparent; border: none; color: var(--app-text-muted, #999); font-size: 14px; padding: 2px 6px; }
.rsd-icon-btn:hover { color: var(--app-text-primary, #333); }
.rsd-spin { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--app-border, #ddd); border-top-color: var(--app-accent, #07b75b); border-radius: 50%; animation: rsd-rotate .8s linear infinite; vertical-align: -2px; margin-right: 6px; }
@keyframes rsd-rotate { to { transform: rotate(360deg); } }
</style>
