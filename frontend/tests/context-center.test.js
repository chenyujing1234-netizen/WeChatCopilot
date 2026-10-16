import { mount, flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import ContextHome from '../pages/index.vue'

const api = {
  getContextSources: vi.fn(),
  getContextSettings: vi.fn(),
  updateContextSettings: vi.fn(),
  triggerWechatSync: vi.fn()
}
let wrapper
let navigateToMock

const sourcesPayload = () => ({
  status: 'ok',
  sources: [
    { source_id: 'wechat', name: '微信数据', enabled: true, state: 'up_to_date', last_saved_at: '2026-10-14T10:00:00', summary: { accounts: 1, account: 'wxid_a', successful_databases: 12 }, planned: false, data_dir: '', data_dir_effective: 'C:\\Users\\dev\\AppData\\Roaming\\ContextBuddy\\output\\databases', archive_content: 'structured' },
    { source_id: 'browser_history', name: '浏览器记录', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '将以浏览器插件方式接入（豆包、Qwen 等浏览记录），插件随应用安装并可更新。' }, planned: true },
    { source_id: 'computer_activity', name: '电脑操作记录', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '记录本机操作行为' }, planned: true },
    { source_id: 'mobile_upload', name: '手机上传', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '配合手机端 NextCloud 应用' }, planned: true },
    { source_id: 'custom_capture', name: '定制浏览器抓取', enabled: false, state: 'planned', last_saved_at: null, summary: { description: '自动生成定制浏览器插件' }, planned: true }
  ]
})

beforeEach(() => {
  navigateToMock = vi.fn()
  vi.stubGlobal('useApi', () => api)
  vi.stubGlobal('navigateTo', navigateToMock)
  api.getContextSources.mockReset().mockImplementation(async () => sourcesPayload())
  api.getContextSettings.mockReset().mockResolvedValue({ status: 'ok', settings: { wechat: { enabled: true } } })
  api.updateContextSettings.mockReset().mockResolvedValue({ status: 'ok', settings: { wechat: { enabled: false } } })
  api.triggerWechatSync.mockReset().mockResolvedValue({ status: 0, errmsg: 'ok', state: 'up_to_date', summary: { accounts: 1 } })
})

afterEach(() => { wrapper?.unmount(); vi.unstubAllGlobals() })

const mountHome = async () => {
  wrapper = mount(ContextHome, { global: { stubs: { GlobalExportDialog: true, WechatDetectionPanel: true } } })
  await flushPromises()
  return wrapper
}

describe('上下文中心首页', () => {
  it('渲染微信卡片与四个规划中的数据源', async () => {
    const w = await mountHome()
    expect(w.text()).toContain('微信数据')
    expect(w.text()).toContain('已是最新')
    expect(w.text()).toContain('2026-10-14T10:00:00')
    expect(w.text()).toContain('浏览器记录')
    expect(w.text()).toContain('将以浏览器插件方式接入')
    const plannedBadges = w.findAll('.rounded-full').filter(b => b.text() === '规划中')
    expect(plannedBadges).toHaveLength(4)
  })

  it('切换自动保存开关调用设置接口', async () => {
    const w = await mountHome()
    await w.find('input[type=checkbox]').setValue(false)
    await flushPromises()
    expect(api.updateContextSettings).toHaveBeenCalled()
    expect(api.updateContextSettings.mock.calls[0][0]).toEqual({ wechat: { enabled: false } })
  })

  it('立即保存调用触发接口并展示结果', async () => {
    const w = await mountHome()
    await w.findAll('button').find(b => b.text() === '立即保存').trigger('click')
    await flushPromises()
    expect(api.triggerWechatSync).toHaveBeenCalledTimes(1)
    expect(w.text()).toContain('本轮保存已完成。')
  })

  it('归档内容默认结构化的数据，切换调用设置接口', async () => {
    const w = await mountHome()
    const select = w.find('select')
    expect(select.element.value).toBe('structured')
    expect(w.text()).toContain('归档内容')
    expect(w.text()).toContain('JSON 与 TXT')
    await select.setValue('databases')
    await flushPromises()
    expect(api.updateContextSettings).toHaveBeenCalledWith({ wechat: { archive_content: 'databases' } })
    expect(w.text()).toContain('归档内容已切换为数据库文件')
  })

  it('归档内容为结构化的数据时，立即保存完成后提示结构化数据已更新', async () => {
    api.triggerWechatSync.mockReset().mockResolvedValue({ status: 0, errmsg: 'ok', state: 'up_to_date', archive_content: 'structured', structured: { ok: true, conversations: 3, messages: 120 } })
    const w = await mountHome()
    await w.findAll('button').find(b => b.text() === '立即保存').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('结构化的数据已更新')
  })

  it('结构化数据更新失败时保存仍算完成，提示下轮自动重试', async () => {
    api.triggerWechatSync.mockReset().mockResolvedValue({ status: 0, errmsg: 'ok', state: 'up_to_date', archive_content: 'structured', structured: { ok: false } })
    const w = await mountHome()
    await w.findAll('button').find(b => b.text() === '立即保存').trigger('click')
    await flushPromises()
    expect(w.text()).toContain('本轮保存已完成')
    expect(w.text()).toContain('下轮保存会自动重试')
  })

  it('显示保存位置的生效路径，默认不显示恢复默认按钮', async () => {
    const w = await mountHome()
    expect(w.text()).toContain('保存位置')
    expect(w.text()).toContain('C:\\Users\\dev\\AppData\\Roaming\\ContextBuddy\\output\\databases')
    expect(w.findAll('button').find(b => b.text() === '恢复默认')).toBeUndefined()
  })

  it('更改保存位置调用设置接口并提示完成', async () => {
    const w = await mountHome()
    const promptMock = vi.spyOn(window, 'prompt').mockReturnValue('D:\\MyWechatData')
    try {
      await w.findAll('button').find(b => b.text() === '更改').trigger('click')
      await flushPromises()
      expect(promptMock).toHaveBeenCalled()
      expect(api.updateContextSettings).toHaveBeenCalledWith({ wechat: { data_dir: 'D:\\MyWechatData' } })
      expect(w.text()).toContain('保存位置已更新')
    } finally {
      promptMock.mockRestore()
    }
  })

  it('自定义路径时显示恢复默认，点击后传空路径', async () => {
    api.getContextSources.mockReset().mockImplementation(async () => {
      const payload = sourcesPayload()
      payload.sources[0].data_dir = 'D:\\MyWechatData'
      payload.sources[0].data_dir_effective = 'D:\\MyWechatData'
      return payload
    })
    const w = await mountHome()
    const resetButton = w.findAll('button').find(b => b.text() === '恢复默认')
    expect(resetButton).toBeDefined()
    await resetButton.trigger('click')
    await flushPromises()
    expect(api.updateContextSettings).toHaveBeenCalledWith({ wechat: { data_dir: '' } })
    expect(w.text()).toContain('已恢复默认保存位置。')
  })

  it('页面文案不出现解密与密钥字样', async () => {
    const w = await mountHome()
    expect(w.text()).not.toContain('解密')
    expect(w.text()).not.toContain('密钥')
  })

  it('账号检测以浮层打开，主界面保留且不发生导航', async () => {
    const w = await mountHome()
    await w.findAll('a').find(a => a.text() === '账号检测').trigger('click')
    await flushPromises()
    expect(navigateToMock).not.toHaveBeenCalled()
    // 主界面（微信卡片）仍在 DOM 中
    expect(w.text()).toContain('微信数据')
    // 浮层容器与检测面板出现
    expect(w.find('.wechat-detection-overlay-card').exists()).toBe(true)
    expect(w.findComponent({ name: 'WechatDetectionPanel' }).exists()).toBe(true)
  })

  it('点击浮层背景关闭账号检测浮层', async () => {
    const w = await mountHome()
    await w.findAll('a').find(a => a.text() === '账号检测').trigger('click')
    await flushPromises()
    await w.find('.wechat-detection-overlay-backdrop').trigger('click')
    await flushPromises()
    expect(w.find('.wechat-detection-overlay-card').exists()).toBe(false)
    expect(w.findComponent({ name: 'WechatDetectionPanel' }).exists()).toBe(false)
  })

  it('查看微信上下文打开独立子窗口，主界面保留且不发生导航', async () => {
    const w = await mountHome()
    const openMock = vi.spyOn(window, 'open').mockReturnValue(null)
    try {
      await w.findAll('button').find(b => b.text() === '查看微信上下文').trigger('click')
      await flushPromises()
      expect(openMock).toHaveBeenCalledWith('/chat', '_blank')
      expect(navigateToMock).not.toHaveBeenCalled()
      // 主界面（微信卡片）仍在 DOM 中
      expect(w.text()).toContain('微信数据')
    } finally {
      openMock.mockRestore()
    }
  })
})
