// frontend/tests/reply-suggestion-dialog.test.js
import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ReplySuggestionDialog from '../components/chat/ReplySuggestionDialog.vue'

const api = {
  getReplySuggestionSettings: vi.fn(async () => ({ workspace_dir: '', enabled: false })),
  generateReplySuggestion: vi.fn(async () => ({
    suggestion: '建议内容', model: 'fixture', filesConsidered: [], contextMessages: 3,
    workspaceUsed: false, workspaceDir: '', workspaceTruncated: false, elapsedMs: 12
  }))
}
let wrapper
beforeEach(() => {
  vi.stubGlobal('useApi', () => api)
  vi.stubGlobal('useSettingsDialog', () => ({ openDialog: vi.fn() }))
})
afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals(); vi.clearAllMocks() })

const mountDialog = (message = { id: 'message_0:msg_x:5', content: '在吗', sender: '对方', fullTime: '2026-01-01 10:00' }) => {
  wrapper = mount(defineComponent({
    setup() { return () => h(ReplySuggestionDialog, { account: 'acc', contact: { username: 'chat', name: '会话' }, message }) }
  }), { attachTo: document.body, global: { stubs: { teleport: true } } })
}

describe('ReplySuggestionDialog', () => {
  it('挂载后自动生成并展示建议', async () => {
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(api.generateReplySuggestion).toHaveBeenCalledWith({
      account: 'acc', conversation: 'chat', anchor_id: 'message_0:msg_x:5', extra_instruction: ''
    })
    expect(wrapper.text()).toContain('建议内容')
    expect(wrapper.text()).toContain('在吗')
  })

  it('无 AI 配置时展示错误与设置入口', async () => {
    api.generateReplySuggestion.mockRejectedValueOnce(Object.assign(
      new Error('尚未配置 AI 服务'), { code: 'ai_not_configured' }))
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    expect(wrapper.text()).toContain('尚未配置 AI 服务')
    expect(wrapper.text()).toContain('去设置 AI 服务')
  })

  it('重新生成携带补充要求', async () => {
    mountDialog()
    await nextTick()
    await new Promise(r => setTimeout(r, 0))
    const input = wrapper.find('input')
    await input.setValue('语气轻松一点')
    await wrapper.findAll('button').find(b => b.text() === '重新生成').trigger('click')
    await new Promise(r => setTimeout(r, 0))
    expect(api.generateReplySuggestion).toHaveBeenLastCalledWith({
      account: 'acc', conversation: 'chat', anchor_id: 'message_0:msg_x:5', extra_instruction: '语气轻松一点'
    })
  })
})
