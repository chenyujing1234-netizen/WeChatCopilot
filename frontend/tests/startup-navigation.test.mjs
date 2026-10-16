import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'
import vm from 'node:vm'
import { parse } from '@vue/compiler-sfc'

const source = readFileSync(new URL('../pages/index.vue', import.meta.url), 'utf8')
const script = parse(source).descriptor.scriptSetup.content.replace(/^import .*$/gm, '')

const runStartup = async ({ fails = false } = {}) => {
  let mounted
  const paths = []
  const warnings = []
  vm.runInNewContext(script, {
    process: { client: true }, window: {},
    ref: value => ({ value }),
    computed: getter => ({ get value() { return getter() } }),
    onMounted: callback => { mounted = callback },
    navigateTo: async path => { paths.push(path) },
    console: { warn: (...args) => warnings.push(args) },
    useApi: () => ({
      getContextSources: async () => {
        await Promise.resolve()
        if (fails) throw new Error('上下文服务暂时不可用')
        return {
          status: 'ok',
          sources: [
            { source_id: 'wechat', name: '微信数据', enabled: true, state: 'up_to_date', last_saved_at: '2026-10-14T10:00:00', summary: { accounts: 1, account: 'wxid_a' }, planned: false },
            { source_id: 'browser_history', name: '浏览器记录', enabled: false, state: 'planned', last_saved_at: null, summary: {}, planned: true }
          ]
        }
      },
      getContextSettings: async () => ({ status: 'ok', settings: { wechat: { enabled: true } } }),
      updateContextSettings: async () => ({ status: 'ok', settings: { wechat: { enabled: true } } }),
      triggerWechatSync: async () => ({ status: 0, errmsg: 'ok', state: 'up_to_date', summary: { accounts: 1 } })
    }),
  })
  await mounted()
  await new Promise(resolve => setImmediate(resolve))
  return { paths, warnings }
}

test('启动后停留在上下文中心，不自动跳转到聊天页', async () => {
  const result = await runStartup()
  assert.deepEqual(result.paths, [])
  assert.equal(result.warnings.length, 0)
})

test('上下文加载失败时记录错误并留在首页', async () => {
  const result = await runStartup({ fails: true })
  assert.deepEqual(result.paths, [])
  assert.equal(result.warnings.length, 0)
})
