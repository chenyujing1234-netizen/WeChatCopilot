<template>
  <div class="min-h-screen">
    <WechatDetectionPanel @close="goHome" />
  </div>
</template>


<script setup>
// 独立路由薄壳：保留 /detection-result 供解密页“重新检测”等入口跳转，
// 检测流程本体在 WechatDetectionPanel 组件中，关闭即返回上下文中心首页。
const goHome = async () => { await navigateTo('/') }
</script>
