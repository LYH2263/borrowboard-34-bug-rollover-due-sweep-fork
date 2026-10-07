<template>
  <div style="padding:16px">
    <h1>设置 · 邻里互借</h1>
    <div class="item settings-row">
      <div>
        <strong>跨日自动续借</strong>
        <div class="muted">
          打开后：应还日当天结束仍未归还，应还日自动加一天且保持在借，不标逾期；
          关闭则当天结束按逾期现算。
        </div>
        <div v-if="msg" class="muted">{{ msg }}</div>
        <div v-if="err" class="err">{{ err }}</div>
      </div>
      <label class="switch">
        <input type="checkbox" :checked="on" :disabled="saving"
               @change="toggle(($event.target))" />
        <span>{{ saving ? '提交中…' : (on ? '已打开' : '已关闭') }}</span>
      </label>
    </div>
    <pre class="muted">{{ raw }}</pre>
  </div>
</template>
<script setup>
import { ref, inject, onMounted } from 'vue'
import { api } from '../api'
const reloadBoard = inject('reloadBoard')
const on = ref(false)
const saving = ref(false)
const msg = ref('')
const err = ref('')
const raw = ref('')

onMounted(async () => {
  const s = await api('/settings')
  on.value = s.auto_renew === 'true'
  raw.value = JSON.stringify(s, null, 2)
})

async function toggle(cb) {
  const want = cb.checked
  saving.value = true; err.value = ''; msg.value = ''
  try {
    // 注入规则写进开关提交：提交成功时后端已按同一规则补续存量借据，
    // 随即重取看板，顶细条与借还记录都来自续借后的同一套数。
    const r = await api('/settings', { method: 'POST', body: JSON.stringify({ auto_renew: want }) })
    on.value = want
    msg.value = want ? `已打开，本次自动续借 ${r.renewed ?? 0} 笔` : '已关闭，此后按逾期现算'
    raw.value = JSON.stringify(r.settings, null, 2)
    await reloadBoard()
  } catch (e) {
    // 续借失败：开关停在失败前，复选框也拨回原位（顶细条保留旧计数）
    cb.checked = on.value
    err.value = '提交失败，设置与应还日均未改动：' + e.message
  } finally {
    saving.value = false
  }
}
</script>
