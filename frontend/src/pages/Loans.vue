<template>
  <div style="padding:16px">
    <h1>借还记录 · 邻里互借</h1>
    <div class="muted" style="margin-bottom:8px">
      自动续借已{{ autoRenew ? '打开' : '关闭' }}：
      {{ autoRenew ? '过应还日未还自动加一天，保持在借' : '过应还日当天结束按逾期现算' }}
    </div>
    <h3>逾期</h3>
    <div v-for="l in data.overdue" :key="'o'+l.id" class="item overdue">
      <strong>{{ l.title }}</strong> · {{ l.borrower }}
      <div class="muted">应还 {{ l.due_date }} · 逾期</div>
    </div>
    <div v-if="!data.overdue.length" class="muted empty">无</div>
    <h3>在借</h3>
    <div v-for="l in data.active" :key="'a'+l.id" class="item" :class="{ renewed: l.renewed }">
      <strong>{{ l.title }}</strong> · {{ l.borrower }}
      <div class="muted">
        应还 {{ l.due_date }}
        <span v-if="l.renewed" class="tag">已自动续借{{ l.renewals ? ' ×' + l.renewals : '' }}</span>
      </div>
    </div>
    <div v-if="!data.active.length" class="muted empty">无</div>
    <h3>已还</h3>
    <div v-for="l in data.returned" :key="'r'+l.id" class="item returned">
      <strong>{{ l.title }}</strong> · {{ l.borrower }}
      <div class="muted">应还 {{ l.due_date || '—' }}</div>
    </div>
  </div>
</template>
<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'
const data = ref({ active: [], overdue: [], returned: [] })
const autoRenew = ref(false)
onMounted(async () => {
  // 借还记录与顶细条同走 /api/loans 扫名单，逾期段和在借段是同一规则分出的两套数
  const [s, d] = await Promise.all([api('/settings'), api('/loans')])
  autoRenew.value = s.auto_renew === 'true'
  data.value = d
})
</script>
