<template>
  <div>
    <div class="status-bar">
      <span>可借 {{ counts.available || 0 }}</span>
      <span>在借 {{ counts.active || 0 }}</span>
      <span>逾期 {{ counts.overdue || 0 }}</span>
      <span v-if="loadErr" class="status-err">刷新失败，显示上次数据：{{ loadErr }}</span>
    </div>
    <nav class="topnav">
      <router-link to="/">看板</router-link>
      <router-link to="/list">上架</router-link>
      <router-link to="/loans">借还记录</router-link>
      <router-link to="/owners">物主</router-link>
      <router-link to="/settings">设置</router-link>
    </nav>
    <router-view @refresh="load" />
  </div>
</template>
<script setup>
import { ref, onMounted, provide } from 'vue'
import { api } from './api'
const counts = ref({})
const renewSweepFork = ref(true)
const board = ref({ available: [], active: [], overdue: [] })
const loadErr = ref('')
async function load() {
  // 拉取/续借失败时保留上一版 board 与顶细条计数，不得闪成空或半截数字
  const prev = board.value
  try {
    const b = await api('/board')
    board.value = b
    counts.value = b.counts || {}
    renewSweepFork.value = !!(b.renew_meta && b.renew_meta.changed > 0)
    loadErr.value = ''
  } catch (e) {
    board.value = prev
    loadErr.value = e.message
  }
}
provide('board', board)
provide('reloadBoard', load)
provide('loadErr', loadErr)
onMounted(load)
</script>
