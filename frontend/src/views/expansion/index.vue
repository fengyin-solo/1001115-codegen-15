<template>
  <section class="page" data-module="expansion">
    <header class="page-head">
      <div>
        <h2>测量回放工作台</h2>
        <p class="page-desc">伸缩缝测量回放按采集导入、整包校验、签认发布、材料建议顺序推进，发布结论写入伸缩缝台账、桥梁档案与材料待办。</p>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <ol class="step-bar">
      <li
        v-for="(step, index) in steps"
        :key="step"
        class="step-item"
        :class="{ active: index === activeStep }"
      >
        {{ index + 1 }}. {{ step }}
      </li>
    </ol>

    <section class="panel">
      <h3 class="panel-title">采集导入</h3>
      <form class="filter-bar" @submit.prevent="importBatch">
        <label class="filter-item">
          <span>所属桥梁</span>
          <input v-model="importForm.所属桥梁" placeholder="与桥梁档案名称一致" />
        </label>
        <label class="filter-item">
          <span>采集时刻</span>
          <input v-model="importForm.采集时刻" placeholder="2026-10-01 08:30" />
        </label>
        <label class="filter-item">
          <span>采集口径</span>
          <input v-model="importForm.采集口径" placeholder="2026版桥面剖面测量口径" />
        </label>
        <label class="filter-item">
          <span>采集单位</span>
          <input v-model="importForm.采集单位" placeholder="桥隧检测中心" />
        </label>
        <label class="filter-item checkbox-item">
          <span>上传中断</span>
          <input v-model="importForm.上传中断" type="checkbox" />
        </label>
        <button class="btn primary" type="submit">导入测量批次</button>
      </form>
      <textarea
        v-model="importForm.读数文本"
        class="reading-input"
        rows="4"
        placeholder="每行一条读数：剖面点,缝编号,缝宽实测,设计缝宽,锚固偏差,仪器类别（可省，默认采集仪器）"
      ></textarea>
      <p class="panel-hint">内容重复按摘要直接消重；勾选「上传中断」时批次保留为待补传，可补传完成。</p>
    </section>

    <section class="panel">
      <h3 class="panel-title">测量批次</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in batchColumns" :key="column">{{ column }}</th>
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in batches" :key="String(row.id)" :class="{ selected: selected?.id === row.id }">
            <td>{{ row.批次号 }}</td>
            <td>{{ row.所属桥梁 }}</td>
            <td>{{ row.采集时刻 }}</td>
            <td>{{ row.采集口径 }}</td>
            <td>{{ (row.读数 ?? []).length }}</td>
            <td>{{ row.状态 }}</td>
            <td>{{ row.摘要 }}</td>
            <td class="row-actions">
              <button class="link" type="button" @click="selectBatch(row)">查看剖面</button>
              <button v-if="row.状态 === '待校验'" class="link" type="button" @click="validateBatch(row)">整包校验</button>
              <button v-if="row.状态 === '待签认'" class="link" type="button" @click="selectBatch(row)">去签认</button>
              <button v-if="row.状态 === '已发布' && !row.材料建议" class="link" type="button" @click="generateSuggestions(row)">材料建议</button>
            </td>
          </tr>
          <tr v-if="!batches.length">
            <td :colspan="batchColumns.length + 1" class="empty-state">暂无测量批次，请先在上方采集导入</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="selected" class="panel">
      <h3 class="panel-title">桥面剖面回放 · {{ selected.批次号 }}（{{ selected.状态 }}）</h3>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in readingColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(reading, index) in selected.读数 ?? []" :key="index">
            <td>{{ reading.剖面点 }}</td>
            <td>{{ reading.缝编号 }}</td>
            <td>{{ reading.缝宽实测 }}</td>
            <td>{{ reading.设计缝宽 }}</td>
            <td>{{ reading.锚固偏差 }}</td>
            <td>{{ reading.仪器类别 }}</td>
            <td>{{ reading.采集时刻 }}</td>
            <td>{{ reading.采集口径 }}</td>
          </tr>
        </tbody>
      </table>

      <template v-if="(selected.校验记录 ?? []).length">
        <h4 class="panel-subtitle">顺序核对结果（缝宽 → 设计 → 锚固偏差）</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th v-for="column in checkColumns" :key="column">{{ column }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(record, index) in selected.校验记录" :key="index">
              <td>{{ record.剖面点 }}</td>
              <td>{{ record.缝编号 }}</td>
              <td>{{ record.结论来源 }}</td>
              <td v-for="step in record.步骤" :key="step.核对项" :class="{ 'warn-text': step.结果 !== '合格' }">
                {{ step.结果 }}
              </td>
              <td :class="{ 'warn-text': record.结论 !== '合格' }">{{ record.结论 }}</td>
            </tr>
          </tbody>
        </table>
      </template>

      <template v-if="(selected.更换建议 ?? []).length">
        <h4 class="panel-subtitle">更换建议</h4>
        <ul class="suggestion-list">
          <li v-for="(item, index) in selected.更换建议" :key="index">
            {{ item.缝编号 }}（{{ item.剖面点 }}）：{{ item.原因 }}，{{ item.建议 }}
          </li>
        </ul>
      </template>

      <div v-if="selected.状态 === '待签认'" class="sign-bar">
        <label class="filter-item">
          <span>签认人</span>
          <input v-model="signer" placeholder="请输入签认人" />
        </label>
        <button class="btn primary" type="button" @click="publishBatch">签认发布</button>
        <span class="panel-hint">校验复核、签认与发布同一事务，失败整体回滚</span>
      </div>

      <template v-if="selected.发布结论">
        <h4 class="panel-subtitle">发布结论</h4>
        <p class="panel-hint">
          {{ selected.发布结论.结论 }} · 台账更新 {{ selected.发布结论.台账更新 }} 条 ·
          档案更新 {{ selected.发布结论.档案更新 }} 座 · 材料待办 {{ selected.发布结论.材料待办 }} 条 ·
          签认人 {{ selected.签认人 }}（{{ selected.签认时刻 }}）
        </p>
      </template>

      <template v-if="selected.状态 === '已发布'">
        <div class="sign-bar">
          <button class="btn" type="button" @click="generateSuggestions(selected)">生成材料建议</button>
        </div>
        <ul v-if="(selected.材料建议 ?? []).length" class="suggestion-list">
          <li v-for="(item, index) in selected.材料建议" :key="index">
            {{ item.材料名称 }} · {{ item.规格建议 }} · 数量 {{ item.数量 }} · 优先级 {{ item.优先级 }}（{{ item.依据 }}）
          </li>
        </ul>
      </template>
    </section>

    <section class="panel">
      <h3 class="panel-title">伸缩缝台账</h3>
      <form class="filter-bar" @submit.prevent="reloadLedger">
        <label class="filter-item">
          <span>缝编号</span>
          <input v-model="ledgerKeyword" placeholder="按缝编号检索" />
        </label>
        <button class="btn" type="submit">查询</button>
      </form>
      <table class="data-table">
        <thead>
          <tr>
            <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in ledger" :key="String(row.id)">
            <td>{{ row.缝编号 }}</td>
            <td>{{ row.所属桥梁 }}</td>
            <td>{{ row.缝类型 }}</td>
            <td>{{ row.设计伸缩量 }}</td>
            <td>{{ row.当前缝宽 }}</td>
            <td>{{ row.堵塞情况 }}</td>
            <td>{{ row.锚固状态 }}</td>
            <td>{{ row.缝状态 ?? row.status }}</td>
            <td>{{ (row.读数历史 ?? []).length }} 条</td>
          </tr>
          <tr v-if="!ledger.length">
            <td :colspan="ledgerColumns.length" class="empty-state">暂无伸缩缝台账数据</td>
          </tr>
        </tbody>
      </table>
    </section>

    <footer class="page-foot">
      <span>共 {{ batches.length }} 个测量批次 · {{ ledgerTotal }} 条台账记录</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, any>

const ENDPOINT = '/api/expansion'
const steps = ['采集导入', '整包校验', '签认发布', '材料建议']
const batchColumns = ['批次号', '所属桥梁', '采集时刻', '采集口径', '读数', '状态', '摘要']
const readingColumns = ['剖面点', '缝编号', '缝宽实测', '设计缝宽', '锚固偏差', '仪器类别', '采集时刻', '采集口径']
const checkColumns = ['剖面点', '缝编号', '结论来源', '缝宽核对', '设计核对', '锚固偏差核对', '结论']
const ledgerColumns = ['缝编号', '所属桥梁', '缝类型', '设计伸缩量', '当前缝宽', '堵塞情况', '锚固状态', '缝状态', '读数历史']

const batches = ref<Row[]>([])
const selected = ref<Row | null>(null)
const ledger = ref<Row[]>([])
const ledgerTotal = ref(0)
const ledgerKeyword = ref('')
const signer = ref('')
const message = ref('')
const messageOk = ref(false)

const importForm = ref({
  所属桥梁: '桥梁档案样例1',
  采集时刻: '2026-10-01 08:30',
  采集口径: '2026版桥面剖面测量口径',
  采集单位: '桥隧检测中心',
  上传中断: false,
  读数文本: 'K0+010,EXPA-0001,41.5,40.0,1.2,采集仪器\nK0+020,EXPA-0003,38.0,40.0,4.6,采集仪器\nK0+020,EXPA-0003,38.4,40.0,4.4,复核仪器',
})

const stats = computed(() => [
  { label: '待校验批次', value: batches.value.filter((b) => b.状态 === '待校验').length },
  { label: '待签认批次', value: batches.value.filter((b) => b.状态 === '待签认').length },
  { label: '已发布批次', value: batches.value.filter((b) => b.状态 === '已发布').length },
  { label: '待补传批次', value: batches.value.filter((b) => b.状态 === '待补传').length },
])

const activeStep = computed(() => {
  if (!selected.value) return -1
  const status = String(selected.value.状态)
  if (status === '待校验' || status === '待补传') return 1
  if (status === '待签认') return 2
  if (status === '已发布') return 3
  return 0
})

function showMessage(ok: boolean, text: string) {
  messageOk.value = ok
  message.value = text
}

function parseReadings(text: string): Row[] {
  return text
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const parts = line.split(/[,，]/).map((part) => part.trim())
      return {
        剖面点: parts[0] ?? '',
        缝编号: parts[1] ?? '',
        缝宽实测: Number(parts[2]),
        设计缝宽: Number(parts[3]),
        锚固偏差: Number(parts[4]),
        仪器类别: parts[5] || '采集仪器',
      }
    })
}

async function callApi(path: string, init?: RequestInit): Promise<Row | null> {
  const response = await request(path, init)
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    showMessage(false, payload.detail ?? '操作未生效，请稍后重试')
    return null
  }
  if (payload && payload.ok === false) {
    showMessage(false, payload.message ?? '操作未生效')
    return null
  }
  return payload
}

async function importBatch() {
  const readings = parseReadings(importForm.value.读数文本)
  if (!readings.length) {
    showMessage(false, '请先填写测量读数，每行一条')
    return
  }
  const payload = await callApi(`${ENDPOINT}/batches`, {
    method: 'POST',
    body: JSON.stringify({
      values: {
        所属桥梁: importForm.value.所属桥梁,
        采集时刻: importForm.value.采集时刻,
        采集口径: importForm.value.采集口径,
        采集单位: importForm.value.采集单位,
        上传中断: importForm.value.上传中断,
        读数: readings,
      },
    }),
  })
  if (!payload) return
  showMessage(true, payload.message ?? '批次已导入')
  await reloadBatches()
  if (payload.entry) selected.value = payload.entry
}

async function selectBatch(row: Row) {
  const payload = await callApi(`${ENDPOINT}/batches/${row.id}`)
  if (payload) selected.value = payload
}

async function validateBatch(row: Row) {
  const payload = await callApi(`${ENDPOINT}/batches/${row.id}/validate`, { method: 'POST', body: '{}' })
  if (!payload) return
  showMessage(true, payload.message ?? '整包校验完成')
  await reloadBatches()
  if (payload.entry) selected.value = payload.entry
}

async function publishBatch() {
  if (!selected.value) return
  if (!signer.value.trim()) {
    showMessage(false, '请先填写签认人')
    return
  }
  const payload = await callApi(`${ENDPOINT}/batches/${selected.value.id}/publish`, {
    method: 'POST',
    body: JSON.stringify({ values: { 签认人: signer.value.trim(), 签认时刻: new Date().toISOString().slice(0, 16).replace('T', ' ') } }),
  })
  if (!payload) return
  showMessage(true, payload.message ?? '签认发布完成')
  signer.value = ''
  await Promise.all([reloadBatches(), reloadLedger()])
  if (payload.entry) selected.value = payload.entry
}

async function generateSuggestions(row: Row) {
  const payload = await callApi(`${ENDPOINT}/batches/${row.id}/suggestions`, { method: 'POST', body: '{}' })
  if (!payload) return
  showMessage(true, payload.message ?? '材料建议已生成')
  await reloadBatches()
  if (payload.entry) selected.value = payload.entry
}

async function reloadBatches() {
  const response = await request(`${ENDPOINT}/batches?size=200`)
  const payload = await response.json()
  batches.value = payload.items ?? []
}

async function reloadLedger() {
  const query = new URLSearchParams()
  if (ledgerKeyword.value.trim()) query.set('keyword', ledgerKeyword.value.trim())
  const response = await request(`${ENDPOINT}?${query.toString()}`)
  const payload = await response.json()
  ledger.value = payload.items ?? []
  ledgerTotal.value = payload.total ?? ledger.value.length
}

onMounted(async () => {
  try {
    await Promise.all([reloadBatches(), reloadLedger()])
  } catch (error) {
    showMessage(false, error instanceof Error ? error.message : '测量回放工作台加载失败')
  }
})
</script>

<style scoped>
.step-bar { display: flex; gap: 8px; list-style: none; padding: 0; margin: 0 0 12px; }
.step-item { flex: 1; text-align: center; padding: 8px 0; border: 1px solid var(--border); border-radius: 6px; background: #fff; color: var(--muted); font-size: 13px; }
.step-item.active { background: var(--brand); border-color: var(--brand); color: #fff; }
.panel { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 12px; }
.panel-title { margin: 0 0 10px; font-size: 14px; }
.panel-subtitle { margin: 12px 0 8px; font-size: 13px; }
.panel-hint { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.reading-input { width: 100%; border: 1px solid var(--border); border-radius: 6px; padding: 8px; font-family: inherit; font-size: 13px; }
.checkbox-item { display: flex; align-items: center; gap: 6px; }
.sign-bar { display: flex; gap: 10px; align-items: flex-end; margin-top: 12px; }
.suggestion-list { margin: 8px 0 0; padding-left: 18px; font-size: 13px; }
.warn-text { color: #b42318; }
.ok-text { color: #067647; }
tr.selected td { background: #eff6ff; }
</style>
