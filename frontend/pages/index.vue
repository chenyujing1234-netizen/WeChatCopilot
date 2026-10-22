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

      <!-- 数据源切换：微信数据 / 浏览器记录 -->
      <div class="mt-8 flex items-center gap-2">
        <button
          type="button"
          class="rounded-full px-4 py-1.5 text-[13px] font-medium transition"
          :class="activeCard === 'wechat' ? 'bg-[#07c160] text-white' : 'bg-white text-[#5f5f5f] border border-[#e8e8e8] hover:border-[#07c160] hover:text-[#07c160]'"
          @click="switchCard('wechat')"
        >
          微信数据
        </button>
        <button
          type="button"
          class="rounded-full px-4 py-1.5 text-[13px] font-medium transition"
          :class="activeCard === 'browser' ? 'bg-[#07c160] text-white' : 'bg-white text-[#5f5f5f] border border-[#e8e8e8] hover:border-[#07c160] hover:text-[#07c160]'"
          @click="switchCard('browser')"
        >
          浏览器记录
        </button>
      </div>

      <!-- 微信上下文卡片 -->
      <section v-if="activeCard === 'wechat'" class="mt-4 rounded-[14px] border border-[#e8e8e8] bg-white p-6 shadow-[0_10px_40px_-24px_rgba(0,0,0,0.35)]">
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

      <!-- 浏览器记录卡片：GPT 平台对话数据（配合「AI对话导出」浏览器扩展） -->
      <section v-else class="mt-4 rounded-[14px] border border-[#e8e8e8] bg-white p-6 shadow-[0_10px_40px_-24px_rgba(0,0,0,0.35)]">
        <div class="flex items-start justify-between gap-4">
          <div class="min-w-0">
            <div class="flex items-center gap-2">
              <h2 class="text-[16px] font-semibold text-[#000000e6]">浏览器记录</h2>
              <span
                class="rounded-full px-2 py-0.5 text-[11px] font-medium"
                :class="extensionInstalled ? 'bg-[#eefbf4] text-[#07964c]' : 'bg-[#fff7e6] text-[#b7791f]'"
              >
                {{ extensionInstalled ? '扩展已安装' : '扩展未安装' }}
              </span>
            </div>
            <p class="mt-2 text-[13px] leading-6 text-[#7F7F7F]">
              配合「AI对话导出」浏览器扩展，在 DeepSeek、豆包、Kimi、腾讯元宝、纳米AI、通义千问、讯飞星火等平台自动抓取对话，一键同步到本机。
            </p>
          </div>
          <label class="flex shrink-0 cursor-pointer items-center gap-2 text-[12px] text-[#5f5f5f]" title="浏览器记录总开关">
            <span>启用</span>
            <input
              type="checkbox"
              class="h-[18px] w-[18px] accent-[#07c160]"
              :checked="browserHistoryEnabled"
              :disabled="togglingBrowser"
              @change="toggleBrowserHistoryEnabled"
            />
          </label>
        </div>

        <!-- 扩展安装管理 -->
        <div class="mt-5 rounded-[10px] bg-[#fafafa] px-4 py-3 text-[12px] text-[#5f5f5f]">
          <div class="flex flex-wrap items-center gap-2">
            <span class="shrink-0 text-[#8a8a8a]">浏览器扩展</span>
            <span class="min-w-0 flex-1 truncate font-medium text-[#222]">{{ extensionStatusText }}</span>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="checkingExtension"
              @click="checkExtension"
            >
              {{ checkingExtension ? '正在检查…' : '检查是否已安装' }}
            </button>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="installingExtension"
              @click="installExtension"
            >
              {{ installingExtension ? '正在准备…' : '安装插件' }}
            </button>
          </div>
          <div v-if="installMessage" class="mt-2 rounded-[8px] bg-white px-3 py-2 leading-6 text-[#222]">
            <p class="whitespace-pre-line">{{ installMessage }}</p>
            <div v-if="extensionDir" class="mt-1 flex items-center gap-2">
              <span class="text-[#8a8a8a]">扩展目录：</span>
              <code class="min-w-0 flex-1 truncate rounded bg-[#f2f2f2] px-2 py-1 text-[11px]">{{ extensionDir }}</code>
              <button
                type="button"
                class="shrink-0 cursor-pointer text-[#07c160] hover:underline"
                @click="copyExtensionDir"
              >
                复制路径
              </button>
              <span v-if="copyMessage" class="shrink-0 text-[#07c160]">{{ copyMessage }}</span>
            </div>
          </div>
        </div>

        <!-- 数据概况 -->
        <div class="mt-3 grid grid-cols-2 gap-3 rounded-[10px] bg-[#fafafa] px-4 py-3 text-[12px] text-[#5f5f5f] md:grid-cols-3">
          <div>
            <div class="text-[#8a8a8a]">已同步会话</div>
            <div class="mt-1 font-medium text-[#222]">{{ browserSummary.total_conversations ?? 0 }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">已同步消息</div>
            <div class="mt-1 font-medium text-[#222]">{{ browserSummary.total_messages ?? 0 }}</div>
          </div>
          <div>
            <div class="text-[#8a8a8a]">最近同步</div>
            <div class="mt-1 font-medium text-[#222]">{{ browserSummary.last_uploaded_at || '尚未同步' }}</div>
          </div>
        </div>

        <!-- 从服务端拉取：按设备 ID 隔离，只拉取本机浏览器上传的数据 -->
        <div class="mt-5 rounded-[10px] bg-[#fafafa] px-4 py-3 text-[12px] text-[#5f5f5f]">
          <div class="flex flex-wrap items-center gap-2">
            <span class="shrink-0 text-[#8a8a8a]">从服务端拉取</span>
            <span class="min-w-0 flex-1 text-[#8a8a8a]">从「AI对话导出」上传服务拉取数据，按设备 ID 隔离，只拉本机浏览器上传的会话</span>
          </div>
          <div class="mt-2 grid gap-2 md:grid-cols-2">
            <label class="flex items-center gap-2">
              <span class="w-16 shrink-0 text-[#8a8a8a]">服务端地址</span>
              <input
                v-model="remoteConfig.server_url"
                type="text"
                placeholder="例如 http://192.168.1.5:8321"
                class="min-w-0 flex-1 rounded-[6px] border border-[#e4e4e4] bg-white px-2 py-1 outline-none transition focus:border-[#07c160]"
                :disabled="remoteBusy"
              />
            </label>
            <label class="flex items-center gap-2">
              <span class="w-16 shrink-0 text-[#8a8a8a]">Token</span>
              <input
                v-model="remoteConfig.token"
                type="text"
                placeholder="服务端 config.json 中的 token"
                class="min-w-0 flex-1 rounded-[6px] border border-[#e4e4e4] bg-white px-2 py-1 outline-none transition focus:border-[#07c160]"
                :disabled="remoteBusy"
              />
            </label>
          </div>
          <div class="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span class="shrink-0 text-[#8a8a8a]">本机设备 ID</span>
            <code class="min-w-0 max-w-full truncate rounded bg-[#f2f2f2] px-2 py-1 text-[11px] text-[#222]">
              {{ remoteDeviceChoice || remoteDeviceId || '未识别（在本机浏览器用扩展上传一次后自动识别）' }}
            </code>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="remoteBusy"
              @click="saveRemoteConfig"
            >
              {{ remoteBusy ? '处理中…' : '保存配置' }}
            </button>
            <button
              type="button"
              class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="remoteBusy"
              @click="loadRemoteDevices"
            >
              查看服务端设备
            </button>
            <button
              type="button"
              class="shrink-0 cursor-pointer font-medium text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="remoteBusy"
              @click="pullRemote"
            >
              {{ remoteBusy ? '正在拉取…' : '从服务端拉取' }}
            </button>
          </div>
          <!-- 服务端设备列表：选择本机的设备（每台浏览器一个 ID） -->
          <div v-if="remoteDevices.length" class="mt-2 space-y-1">
            <div class="text-[#8a8a8a]">服务端已见设备（点击选中本机的设备）：</div>
            <label
              v-for="d in remoteDevices"
              :key="d.device_id"
              class="flex cursor-pointer items-center gap-2 rounded-[6px] bg-white px-2 py-1"
            >
              <input v-model="remoteDeviceChoice" type="radio" :value="d.device_id" class="accent-[#07c160]" />
              <span class="min-w-0 flex-1 truncate text-[#222]">{{ d.device_id }}</span>
              <span class="shrink-0 text-[#8a8a8a]">{{ d.conversations }} 个会话 / {{ d.messages }} 条消息</span>
            </label>
          </div>
          <p v-if="remoteMessage" class="mt-2 leading-5" :class="remoteMessageOk ? 'text-[#07964c]' : 'text-red-500'">{{ remoteMessage }}</p>
        </div>

        <!-- 已同步会话：点击行展开查看消息，可下载为 Markdown（一个会话一个 .md） -->
        <div class="mt-5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <h3 class="text-[13px] font-semibold text-[#000000e6]">已同步会话（点击行展开查看内容）</h3>
            <button
              type="button"
              class="cursor-pointer text-[12px] text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
              :disabled="convDownloading || !browserConversations.length"
              @click="downloadAllConversations"
            >
              {{ convDownloading ? '正在下载…' : '下载全部（zip）' }}
            </button>
          </div>

          <!-- 平台筛选：全部 + 已有同步数据的平台 -->
          <div v-if="convFilterOptions.length > 1" class="mt-2 flex flex-wrap gap-1.5">
            <button
              v-for="opt in convFilterOptions"
              :key="opt.code || 'all'"
              type="button"
              class="rounded-full px-2.5 py-1 text-[11px] transition"
              :class="convPlatformFilter === opt.code ? 'bg-[#07c160] text-white' : 'bg-[#f2f2f2] text-[#5f5f5f] hover:text-[#07c160]'"
              @click="changeConvFilter(opt.code)"
            >
              {{ opt.name }}
            </button>
          </div>

          <div v-if="convMessage" class="mt-2 text-[12px] leading-5 text-[#07964c]">{{ convMessage }}</div>

          <div v-if="convLoading" class="mt-3 text-[12px] text-[#8a8a8a]">正在加载会话列表…</div>
          <div v-else-if="!browserConversations.length" class="mt-3 text-[12px] text-[#8a8a8a]">
            暂无已同步会话，在 GPT 平台用扩展上传对话后会自动出现在这里。
          </div>
          <div v-else class="mt-3 overflow-hidden rounded-[10px] border border-[#e8e8e8]">
            <div v-for="c in browserConversations" :key="c.id">
              <div
                class="flex cursor-pointer items-center gap-2 border-b border-[#f2f2f2] px-4 py-2.5 text-[12px] hover:bg-[#fafafa]"
                @click="toggleConversation(c)"
              >
                <span class="shrink-0 rounded bg-[#f2f2f2] px-1.5 py-0.5 text-[11px] text-[#5f5f5f]">{{ c.platform_name }}</span>
                <span class="min-w-0 flex-1 truncate font-medium text-[#222]" :title="c.title">{{ c.title || '未命名会话' }}</span>
                <span class="shrink-0 text-[#8a8a8a]">{{ c.message_count }} 条</span>
                <span class="hidden shrink-0 text-[#8a8a8a] md:inline">{{ c.received_at || '' }}</span>
                <span class="shrink-0 text-[#8a8a8a]">{{ expandedConvId === c.id ? '▲' : '▼' }}</span>
                <button
                  type="button"
                  class="shrink-0 cursor-pointer text-[#07c160] hover:underline disabled:cursor-not-allowed disabled:opacity-60"
                  :disabled="convDownloading"
                  @click.stop="downloadConversation(c)"
                >
                  下载 .md
                </button>
              </div>
              <div v-if="expandedConvId === c.id" class="border-b border-[#f2f2f2] bg-[#fafafa] px-4 py-3">
                <div v-if="convDetailLoading" class="text-[12px] text-[#8a8a8a]">正在加载消息…</div>
                <div v-else class="max-h-[320px] space-y-3 overflow-y-auto">
                  <div v-for="(m, i) in convDetail?.messages || []" :key="i" class="rounded-[8px] bg-white px-3 py-2">
                    <div class="flex items-center gap-2 text-[11px] text-[#8a8a8a]">
                      <span class="font-medium" :class="m.role === 'user' ? 'text-[#07964c]' : 'text-[#1677ff]'">
                        {{ m.role === 'user' ? '👤 用户' : m.role === 'assistant' ? '🤖 助手' : '📋 系统' }}
                      </span>
                      <span v-if="m.msg_time">{{ m.msg_time }}</span>
                    </div>
                    <pre class="mt-1 max-h-[220px] overflow-y-auto whitespace-pre-wrap break-words font-sans text-[12px] leading-5 text-[#222]">{{ m.content || '（无内容）' }}</pre>
                    <details v-if="m.thinking_content" class="mt-1">
                      <summary class="cursor-pointer text-[11px] text-[#8a8a8a]">思考过程</summary>
                      <pre class="mt-1 whitespace-pre-wrap break-words text-[11px] leading-5 text-[#8a8a8a]">{{ m.thinking_content }}</pre>
                    </details>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <button
            v-if="browserConversations.length < convTotal"
            type="button"
            class="mt-2 cursor-pointer text-[12px] text-[#07c160] hover:underline"
            @click="loadMoreConversations"
          >
            加载更多（已显示 {{ browserConversations.length }}/{{ convTotal }}）
          </button>
        </div>

        <!-- 各 GPT 平台：点击打开平台网站，装好扩展后打开对话即自动抓取 -->
        <div class="mt-5">
          <div class="flex items-center justify-between">
            <h3 class="text-[13px] font-semibold text-[#000000e6]">GPT 平台（点击打开，扩展自动抓取对话）</h3>
            <span class="text-[11px] text-[#8a8a8a]">在平台打开对话后，用页面右侧悬浮按钮上传</span>
          </div>
          <div class="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
            <div
              v-for="p in browserPlatforms"
              :key="p.code"
              class="flex cursor-pointer items-center justify-between gap-3 rounded-[10px] border border-[#e8e8e8] px-4 py-2.5 text-[12px] transition hover:border-[#07c160]"
              :title="`打开 ${p.name}`"
              @click="openPlatform(p)"
            >
              <div class="min-w-0">
                <div class="font-medium text-[#222]">{{ p.name }}</div>
                <div class="mt-0.5 text-[11px] text-[#8a8a8a]">{{ p.url }}</div>
              </div>
              <div class="shrink-0 text-right">
                <div class="font-medium text-[#222]">
                  {{ p.conversations ? `${p.conversations} 会话 / ${p.messages} 条消息` : '暂无同步数据' }}
                </div>
                <div class="mt-0.5 text-[11px] text-[#8a8a8a]">{{ p.last_received_at ? `最近同步：${p.last_received_at}` : '未同步' }}</div>
              </div>
            </div>
          </div>
        </div>
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

const { getContextSources, getContextSettings, updateContextSettings, triggerWechatSync, getBrowserHistoryStatus, prepareBrowserExtension, openBrowserExtensionPage, openGptPlatform, getBrowserConversations, getBrowserConversation, downloadBrowserExport, getBrowserRemoteConfig, saveBrowserRemoteConfig, listBrowserRemoteDevices, pullBrowserRemoteConversations } = useApi()

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
const browserSource = computed(() => sources.value.find(s => s.source_id === 'browser_history') || null)
const plannedSources = computed(() => sources.value.filter(s => !['wechat', 'browser_history'].includes(s.source_id)))
const wechatSummary = computed(() => wechatSource.value?.summary || {})

// ---------- 浏览器记录（GPT 平台对话抓取扩展） ----------
const activeCard = ref('wechat')
const checkingExtension = ref(false)
const installingExtension = ref(false)
const togglingBrowser = ref(false)
const browserHistoryEnabled = ref(true)
const extensionInstall = ref(null) // {installed, installations[], extension_dir}
const extensionDir = ref('')
const installMessage = ref('')
const copyMessage = ref('')

// 全量平台列表（与后端一致）：无数据的也展示，方便点击打开
const ALL_GPT_PLATFORMS = [
  { code: 'deepseek', name: 'DeepSeek', url: 'https://chat.deepseek.com/' },
  { code: 'ncn', name: '纳米AI', url: 'https://bot.n.cn/' },
  { code: 'yuanbao', name: '腾讯元宝', url: 'https://yuanbao.tencent.com/' },
  { code: 'kimi', name: 'Kimi', url: 'https://kimi.com/' },
  { code: 'qianwen', name: '通义千问', url: 'https://www.tongyi.com/' },
  { code: 'iflytek', name: '讯飞星火', url: 'https://xinghuo.xfyun.cn/' },
  { code: 'doubao', name: '豆包', url: 'https://www.doubao.com/chat/' }
]

const browserSummary = computed(() => browserSource.value?.summary || {})
const extensionInstalled = computed(() => !!(extensionInstall.value?.installed || browserSummary.value?.extension?.installed))
const extensionStatusText = computed(() => {
  const info = extensionInstall.value || browserSummary.value?.extension
  const inst = info?.installations?.[0]
  if (info?.installed) return inst ? `${info.extension_name} · ${inst.browser} ${inst.profile}` : `${info.extension_name} · 已安装`
  return '未检测到「AI对话导出」扩展'
})
const browserPlatforms = computed(() => {
  const stats = {}
  for (const p of browserSummary.value?.platforms || []) stats[p.code] = p
  return ALL_GPT_PLATFORMS.map(p => ({ ...p, ...(stats[p.code] || {}) }))
})

// 已同步会话列表：本机数据库读取，支持平台筛选/分页/展开查看/下载 Markdown
const CONV_PAGE_SIZE = 50
const browserConversations = ref([])
const convTotal = ref(0)
const convPlatformFilter = ref('')
const convLoading = ref(false)
const convDownloading = ref(false)
const expandedConvId = ref(null)
const convDetail = ref(null)
const convDetailLoading = ref(false)
const convMessage = ref('')

const convFilterOptions = computed(() => {
  const list = [{ code: '', name: '全部' }]
  for (const p of browserSummary.value?.platforms || []) list.push({ code: p.code, name: p.name })
  return list
})

const loadConversations = async (reset = false) => {
  convLoading.value = true
  try {
    const offset = reset ? 0 : browserConversations.value.length
    const resp = await getBrowserConversations({
      platform: convPlatformFilter.value || undefined,
      limit: CONV_PAGE_SIZE,
      offset
    })
    convTotal.value = resp?.total || 0
    const items = resp?.conversations || []
    browserConversations.value = reset ? items : [...browserConversations.value, ...items]
  } catch (e) {
    error.value = e?.message || '加载已同步会话失败'
  } finally {
    convLoading.value = false
  }
}

const loadMoreConversations = () => loadConversations(false)

const changeConvFilter = (code) => {
  if (convPlatformFilter.value === code) return
  convPlatformFilter.value = code
  expandedConvId.value = null
  convDetail.value = null
  void loadConversations(true)
}

const toggleConversation = async (c) => {
  if (expandedConvId.value === c.id) {
    expandedConvId.value = null
    convDetail.value = null
    return
  }
  expandedConvId.value = c.id
  convDetailLoading.value = true
  convDetail.value = null
  try {
    convDetail.value = await getBrowserConversation(c.id)
  } catch (e) {
    error.value = e?.message || '加载会话消息失败'
  } finally {
    convDetailLoading.value = false
  }
}

const downloadConversation = async (c) => {
  if (convDownloading.value) return
  convDownloading.value = true
  try {
    const filename = await downloadBrowserExport({ ids: String(c.id) })
    convMessage.value = `已下载：${filename}`
  } catch (e) {
    convMessage.value = e?.message || '下载会话失败'
  } finally {
    convDownloading.value = false
  }
}

const downloadAllConversations = async () => {
  if (convDownloading.value || !browserConversations.value.length) return
  convDownloading.value = true
  try {
    const params = convPlatformFilter.value ? { platform: convPlatformFilter.value } : {}
    const filename = await downloadBrowserExport(params)
    convMessage.value = `已下载：${filename}`
  } catch (e) {
    convMessage.value = e?.message || '下载会话失败'
  } finally {
    convDownloading.value = false
  }
}

// 从服务端拉取：按 device_id 隔离，只拉本机浏览器上传的会话
const remoteConfig = ref({ server_url: '', token: '' })
const remoteDeviceId = ref('')
const remoteDeviceChoice = ref('')
const remoteDevices = ref([])
const remoteBusy = ref(false)
const remoteMessage = ref('')
const remoteMessageOk = ref(true)

const loadRemoteConfig = async () => {
  try {
    const resp = await getBrowserRemoteConfig()
    remoteConfig.value = { server_url: resp?.server_url || '', token: resp?.token || '' }
    remoteDeviceId.value = resp?.local_device_id || ''
    remoteDeviceChoice.value = resp?.device_id || resp?.local_device_id || ''
  } catch {
    // 配置读取失败不打扰用户（本地无配置时静默）
  }
}

const saveRemoteConfig = async () => {
  remoteBusy.value = true
  try {
    const resp = await saveBrowserRemoteConfig({
      server_url: remoteConfig.value.server_url,
      token: remoteConfig.value.token,
      device_id: remoteDeviceChoice.value
    })
    remoteDeviceId.value = resp?.local_device_id || remoteDeviceId.value
    remoteMessage.value = '配置已保存'
    remoteMessageOk.value = true
  } catch (e) {
    remoteMessage.value = e?.message || '保存配置失败'
    remoteMessageOk.value = false
  } finally {
    remoteBusy.value = false
  }
}

const loadRemoteDevices = async () => {
  remoteBusy.value = true
  try {
    const resp = await listBrowserRemoteDevices({
      server_url: remoteConfig.value.server_url,
      token: remoteConfig.value.token
    })
    remoteDevices.value = resp?.devices || []
    if (!remoteDeviceChoice.value && remoteDevices.value.length === 1) {
      remoteDeviceChoice.value = remoteDevices.value[0].device_id
    }
    remoteMessage.value = remoteDevices.value.length
      ? `服务端共 ${remoteDevices.value.length} 个设备，请选中本机的设备后拉取`
      : '服务端暂无设备数据（需先用扩展上传一次）'
    remoteMessageOk.value = !!remoteDevices.value.length
  } catch (e) {
    remoteMessage.value = e?.message || '获取服务端设备列表失败'
    remoteMessageOk.value = false
  } finally {
    remoteBusy.value = false
  }
}

const pullRemote = async () => {
  remoteBusy.value = true
  try {
    const resp = await pullBrowserRemoteConversations({
      server_url: remoteConfig.value.server_url,
      token: remoteConfig.value.token,
      device_id: remoteDeviceChoice.value || undefined
    })
    remoteMessage.value = `拉取完成：服务端 ${resp?.server_total ?? 0} 个会话，导入 ${resp?.imported ?? 0} 个（跳过 ${resp?.skipped ?? 0}，失败 ${resp?.failed ?? 0}）`
    remoteMessageOk.value = true
    await loadConversations(true)
  } catch (e) {
    remoteMessage.value = e?.message || '从服务端拉取失败'
    remoteMessageOk.value = false
  } finally {
    remoteBusy.value = false
  }
}

const switchCard = (card) => {
  activeCard.value = card
  if (card === 'browser') {
    void checkExtension(false)
    void loadConversations(true)
    void loadRemoteConfig()
  }
}

const checkExtension = async (showResult = true) => {
  checkingExtension.value = true
  try {
    const resp = await getBrowserHistoryStatus()
    extensionInstall.value = resp || null
    if (resp?.extension_dir) extensionDir.value = resp.extension_dir
    if (showResult) {
      installMessage.value = resp?.installed
        ? `已检测到扩展（${(resp.installations || []).map(i => `${i.browser} ${i.profile}`).join('、') || '已安装'}），在 GPT 平台打开对话即可抓取。`
        : '未检测到扩展，请点「安装插件」按步骤安装。'
    }
    await reload()
  } catch (e) {
    if (showResult) installMessage.value = e?.message || '检查扩展安装状态失败'
  } finally {
    checkingExtension.value = false
  }
}

const installExtension = async () => {
  installingExtension.value = true
  copyMessage.value = ''
  try {
    const resp = await prepareBrowserExtension()
    extensionDir.value = resp?.extension_dir || ''
    const pageResp = await openBrowserExtensionPage('chrome')
    const opened = pageResp?.ok !== false
    const alreadyRunning = pageResp?.already_running === true
    installMessage.value = [
      !opened
        ? '插件副本已生成。未能自动打开浏览器，请先手动打开 Chrome，在地址栏输入 chrome://extensions/ 进入扩展管理页，再按以下步骤完成安装：'
        : alreadyRunning
          ? '插件副本已生成（上传地址已指向本机）。检测到 Chrome 已在运行，未重复启动，请在已打开的 Chrome 中进入扩展管理页（地址栏输入 chrome://extensions/），按以下步骤完成安装：'
          : '插件副本已生成（上传地址已指向本机），已打开浏览器扩展管理页，请按以下步骤完成安装：',
      '1. 在扩展管理页右上角打开「开发者模式」；',
      '2. 点「加载已解压的扩展程序」，选择下面这个目录；',
      '3. 安装完成后回到这里点「检查是否已安装」确认。'
    ].join('\n')
  } catch (e) {
    installMessage.value = e?.message || '生成扩展副本失败'
  } finally {
    installingExtension.value = false
  }
}

const copyExtensionDir = async () => {
  try {
    await navigator.clipboard.writeText(extensionDir.value)
    copyMessage.value = '已复制'
  } catch {
    copyMessage.value = '复制失败，请手动选中路径复制'
  }
}

const toggleBrowserHistoryEnabled = async (event) => {
  const enabled = !!event?.target?.checked
  togglingBrowser.value = true
  browserHistoryEnabled.value = enabled
  try {
    await updateContextSettings({ browser_history: { enabled } })
    await reload()
  } catch (e) {
    browserHistoryEnabled.value = !enabled
    error.value = e?.message || '保存浏览器记录开关失败'
  } finally {
    togglingBrowser.value = false
  }
}

const openPlatform = async (p) => {
  try {
    await openGptPlatform(p.url)
  } catch (e) {
    error.value = e?.message || '打开平台失败'
  }
}

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
    browserHistoryEnabled.value = settingsResp?.settings?.browser_history
      ? !!(settingsResp.settings.browser_history.enabled)
      : true
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
