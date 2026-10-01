<template>
  <section class="page" data-module="expansion">
    <header class="page-head">
      <div>
        <h2>伸缩缝测量回放工作台</h2>
        <p class="page-desc">
          按 采集导入 → 整包校验 → 签认发布 → 材料建议 顺序推进，前序未签认不得跳级；
          发布结论一次写入伸缩缝台账、桥梁档案与材料待办，失败整体回滚。
        </p>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <ol v-if="selected" class="step-bar">
      <li v-for="(step, index) in steps" :key="step" :class="stepClass(index)">
        <span class="step-no">{{ index + 1 }}</span>{{ step }}
      </li>
    </ol>

    <div class="workbench">
      <aside class="batch-panel">
        <details class="import-box" open>
          <summary>采集导入</summary>
          <label class="form-item">
            <span>所属桥梁（须存在于桥梁档案）</span>
            <input v-model="importForm.所属桥梁" placeholder="如：桥梁档案样例1" />
          </label>
          <label class="form-item">
            <span>采集日期</span>
            <input v-model="importForm.采集日期" type="date" />
          </label>
          <label class="form-item">
            <span>采集仪器</span>
            <input v-model="importForm.采集仪器" placeholder="如：数显缝宽仪 SW-2" />
          </label>
          <label class="form-item">
            <span>采集口径</span>
            <input v-model="importForm.采集口径" placeholder="如：JTG/T H21 常温20℃换算" />
          </label>

          <table class="data-table reading-editor">
            <thead>
              <tr>
                <th>测点桩号</th><th>缝编号</th><th>实测缝宽</th><th>设计缝宽</th>
                <th>锚固偏差</th><th>采集时刻</th><th>采集口径</th><th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(row, index) in importReadings" :key="index">
                <td><input v-model="row.测点桩号" placeholder="K12+300" /></td>
                <td><input v-model="row.缝编号" placeholder="EXPA-0001" /></td>
                <td><input v-model="row.实测缝宽" type="number" step="0.1" /></td>
                <td><input v-model="row.设计缝宽" type="number" step="0.1" /></td>
                <td><input v-model="row.锚固偏差" type="number" step="0.1" /></td>
                <td><input v-model="row.采集时刻" placeholder="2026-10-01 09:00" /></td>
                <td><input v-model="row.采集口径" /></td>
                <td><button class="link" type="button" @click="importReadings.splice(index, 1)">删除</button></td>
              </tr>
            </tbody>
          </table>
          <div class="import-actions">
            <button class="btn ghost" type="button" @click="addReading">添加测点</button>
            <button class="btn ghost" type="button" @click="fillSample">载入示例</button>
            <button class="btn primary" type="button" @click="importBatch">导入采集包</button>
          </div>
          <p class="hint">上传中断后批次保留在待发布列表；内容重复的采集包按摘要直接消重。</p>
        </details>

        <h3 class="panel-title">待发布批次</h3>
        <ul class="batch-list">
          <li
            v-for="batch in pendingBatches"
            :key="batch.id"
            :class="{ active: selected?.id === batch.id }"
            @click="selectBatch(batch.id)"
          >
            <strong>{{ batch.批次编号 }}</strong>
            <span>{{ batch.所属桥梁 }} · {{ batch.采集日期 }}</span>
            <em :class="['badge', statusClass(batch.status)]">{{ batch.status }}</em>
          </li>
          <li v-if="!pendingBatches.length" class="empty-state">暂无待发布批次</li>
        </ul>

        <h3 class="panel-title">已发布批次</h3>
        <ul class="batch-list">
          <li
            v-for="batch in publishedBatches"
            :key="batch.id"
            :class="{ active: selected?.id === batch.id }"
            @click="selectBatch(batch.id)"
          >
            <strong>{{ batch.批次编号 }}</strong>
            <span>{{ batch.所属桥梁 }} · 建议更换 {{ batch.发布结论?.建议更换数量 ?? 0 }} 道</span>
            <em class="badge done">已发布</em>
          </li>
          <li v-if="!publishedBatches.length" class="empty-state">暂无已发布批次</li>
        </ul>
      </aside>

      <main v-if="selected" class="batch-detail">
        <header class="detail-head">
          <div>
            <h3>{{ selected.批次编号 }} · {{ selected.所属桥梁 }}</h3>
            <p class="page-desc">
              采集 {{ selected.采集日期 }} · {{ selected.采集仪器 }} · 批次口径 {{ selected.采集口径 }}
              <template v-if="selected.签认人"> · 签认 {{ selected.签认人 }} {{ selected.签认时间 }}</template>
            </p>
          </div>
          <em :class="['badge', statusClass(selected.status)]">{{ selected.status }}</em>
        </header>

        <div v-if="selected.readings?.length" class="profile-strip">
          <div
            v-for="reading in selected.readings"
            :key="reading.测点桩号"
            class="profile-point"
            :class="verdictClass(reading.测点桩号)"
          >
            <span class="profile-stake">{{ reading.测点桩号 }}</span>
            <span class="profile-joint">{{ reading.缝编号 }}</span>
          </div>
        </div>

        <h4 class="section-title">桥面剖面顺序核对（缝宽 / 设计 / 锚固偏差）</h4>
        <table class="data-table">
          <thead>
            <tr>
              <th>序</th><th>测点桩号</th><th>缝编号</th><th>实测缝宽</th><th>设计缝宽</th>
              <th>缝宽偏差</th><th>锚固偏差</th><th>采集时刻</th><th>采集口径</th>
              <template v-if="selected.status === '待签认'">
                <th>复核缝宽</th><th>复核锚固偏差</th><th>复核结论</th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(reading, index) in selected.readings" :key="reading.测点桩号">
              <td>{{ index + 1 }}</td>
              <td>{{ reading.测点桩号 }}</td>
              <td>{{ reading.缝编号 }}</td>
              <td>{{ reading.实测缝宽 }}</td>
              <td>{{ reading.设计缝宽 }}</td>
              <td :class="{ 'over-limit': isWidthOver(reading) }">{{ reading.缝宽偏差 ?? '—' }}</td>
              <td :class="{ 'over-limit': isAnchorOver(reading) }">{{ reading.锚固偏差 }}</td>
              <td>{{ reading.采集时刻 }}</td>
              <td>{{ reading.采集口径 }}</td>
              <template v-if="selected.status === '待签认'">
                <td><input v-model="reviewInputs[reading.测点桩号].复核缝宽" class="review-input" type="number" step="0.1" placeholder="留空用实测" /></td>
                <td><input v-model="reviewInputs[reading.测点桩号].复核锚固偏差" class="review-input" type="number" step="0.1" placeholder="留空用实测" /></td>
                <td>
                  <select v-model="reviewInputs[reading.测点桩号].复核结论" class="review-input">
                    <option value="">按偏差判定</option>
                    <option value="正常">正常</option>
                    <option value="建议更换">建议更换</option>
                  </select>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
        <p class="hint">复核仪器结论优先于历史读数；历史读数保留当时采集口径，不被改写。</p>

        <div v-if="selected.校验结果" class="result-box" :class="selected.校验结果.通过 ? 'pass' : 'fail'">
          <strong>整包校验{{ selected.校验结果.通过 ? '通过' : '未通过' }}</strong>
          <span class="hint">{{ selected.校验结果.校验时间 }}</span>
          <ul v-if="selected.校验结果.问题.length">
            <li v-for="problem in selected.校验结果.问题" :key="problem">{{ problem }}</li>
          </ul>
        </div>

        <div v-if="selected.status === '待签认'" class="sign-box">
          <label class="form-item">
            <span>签认人</span>
            <input v-model="signForm.签认人" placeholder="必填" />
          </label>
          <label class="form-item">
            <span>签认意见</span>
            <input v-model="signForm.签认意见" placeholder="选填" />
          </label>
        </div>

        <div v-if="selected.发布结论" class="result-box pass">
          <strong>发布结论（{{ selected.发布时间 }}）</strong>
          <p>
            正常 {{ selected.发布结论.正常数量 }} 道、建议更换 {{ selected.发布结论.建议更换数量 }} 道；
            已写入伸缩缝台账 {{ selected.发布结论.台账写入 }} 条、桥梁档案「{{ selected.发布结论.桥梁档案 }}」、
            材料待办 {{ selected.发布结论.材料待办 }} 条。
          </p>
          <table class="data-table">
            <thead>
              <tr><th>测点桩号</th><th>缝编号</th><th>采用缝宽</th><th>采用锚固偏差</th><th>数据来源</th><th>结论</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in selected.发布结论.结论明细" :key="item.测点桩号">
                <td>{{ item.测点桩号 }}</td>
                <td>{{ item.缝编号 }}</td>
                <td>{{ item.采用缝宽 }}</td>
                <td>{{ item.采用锚固偏差 }}</td>
                <td>{{ item.数据来源 }}</td>
                <td :class="item.结论 === '建议更换' ? 'over-limit' : ''">{{ item.结论 }}</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div v-if="selected.材料建议" class="result-box">
          <strong>材料建议（已同步材料计划）</strong>
          <table v-if="selected.材料建议.length" class="data-table">
            <thead>
              <tr><th>缝编号</th><th>测点桩号</th><th>建议材料</th><th>规格型号</th><th>数量</th><th>依据</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in selected.材料建议" :key="item.缝编号">
                <td>{{ item.缝编号 }}</td>
                <td>{{ item.测点桩号 }}</td>
                <td>{{ item.建议材料 }}</td>
                <td>{{ item.规格型号 }}</td>
                <td>{{ item.数量 }} {{ item.单位 }}</td>
                <td>{{ item.依据 }}</td>
              </tr>
            </tbody>
          </table>
          <p v-else class="hint">本批次无建议更换测点，材料建议为空。</p>
        </div>

        <div class="action-row">
          <button
            v-if="selected.status === '待校验' || selected.status === '校验失败'"
            class="btn primary"
            type="button"
            @click="doValidate"
          >整包校验</button>
          <button
            v-if="selected.status === '待签认'"
            class="btn primary"
            type="button"
            @click="doPublish"
          >签认发布（一次写入台账/档案/材料待办）</button>
          <button
            v-if="selected.status === '已发布' && !selected.材料建议"
            class="btn primary"
            type="button"
            @click="doSuggest"
          >生成材料建议</button>
          <button
            v-if="selected.status !== '已发布'"
            class="btn"
            type="button"
            disabled
            title="前序未签认，不得跳级生成建议"
          >材料建议（待签认发布）</button>
        </div>
      </main>
      <main v-else class="batch-detail empty-state">从左侧选择待发布批次，或导入新的采集包</main>
    </div>

    <h3 class="panel-title">伸缩缝台账（发布结论落点）</h3>
    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in ledgerColumns" :key="column">{{ column }}</th>
          <th>处置动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in ledgerRows" :key="String(row.id)">
          <td v-for="column in ledgerColumns" :key="column">{{ row[column] ?? '—' }}</td>
          <td class="row-actions">
            <button
              v-for="action in ledgerActions"
              :key="action"
              class="link"
              type="button"
              @click="runLedgerAction(action, row)"
            >{{ action }}</button>
          </td>
        </tr>
        <tr v-if="!ledgerRows.length">
          <td :colspan="ledgerColumns.length + 1" class="empty-state">暂无台账数据</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ ledgerRows.length }} 条台账 · {{ batches.length }} 个测量批次</span>
      <span v-if="message" :class="messageOk ? 'ok-text' : 'error-text'">{{ message }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Reading = {
  测点桩号: string
  缝编号: string
  实测缝宽: number | string | null
  设计缝宽: number | string | null
  锚固偏差: number | string | null
  采集时刻: string
  采集口径: string
  复核缝宽?: number | null
  复核锚固偏差?: number | null
  复核结论?: string | null
  缝宽偏差?: number | null
}

type Conclusion = {
  测点桩号: string
  缝编号: string
  采用缝宽: number
  采用锚固偏差: number
  数据来源: string
  结论: string
}

type Suggestion = {
  缝编号: string
  测点桩号: string
  建议材料: string
  规格型号: string
  数量: number
  单位: string
  依据: string
}

type Batch = {
  id: number
  批次编号: string
  所属桥梁: string
  采集日期: string
  采集仪器: string
  采集口径: string
  status: string
  读数条数?: number
  readings?: Reading[]
  校验结果?: { 通过: boolean; 问题: string[]; 校验时间: string } | null
  签认人?: string | null
  签认时间?: string | null
  发布时间?: string | null
  发布结论?: {
    结论明细: Conclusion[]
    正常数量: number
    建议更换数量: number
    台账写入: number
    桥梁档案: string
    材料待办: number
  } | null
  材料建议?: Suggestion[] | null
}

type LedgerRow = Record<string, string | number | null> & { id: number }

const ENDPOINT = '/api/expansion'
const WIDTH_TOLERANCE = 10
const ANCHOR_TOLERANCE = 5
const steps = ['采集导入', '整包校验', '签认发布', '材料建议']
const ledgerColumns = ['缝编号', '所属桥梁', '缝类型', '设计伸缩量', '当前缝宽', '锚固状态', '缝状态', '复核结论', '最近复核批次', '采集口径']
const ledgerActions = ['清理堵塞', '修补锚固', '更换伸缩缝']

const batches = ref<Batch[]>([])
const selected = ref<Batch | null>(null)
const ledgerRows = ref<LedgerRow[]>([])
const message = ref('')
const messageOk = ref(true)

const importForm = ref({ 所属桥梁: '', 采集日期: '', 采集仪器: '', 采集口径: '' })
const importReadings = ref<Reading[]>([])
const signForm = ref({ 签认人: '', 签认意见: '' })
const reviewInputs = ref<Record<string, { 复核缝宽: string | number; 复核锚固偏差: string | number; 复核结论: string }>>({})

const pendingBatches = computed(() => batches.value.filter(b => ['待校验', '待签认', '校验失败'].includes(b.status)))
const publishedBatches = computed(() => batches.value.filter(b => b.status === '已发布'))
const stats = computed(() => [
  { label: '待发布批次', value: pendingBatches.value.length },
  { label: '已发布批次', value: publishedBatches.value.length },
  { label: '待更换缝', value: ledgerRows.value.filter(row => row['缝状态'] === '待更换').length },
  { label: '材料待办', value: batches.value.reduce((sum, b) => sum + (b.发布结论?.材料待办 ?? 0), 0) },
])

function stepClass(index: number): string {
  const batch = selected.value
  if (!batch) return 'todo'
  const done = [
    true,
    ['待签认', '已发布'].includes(batch.status),
    batch.status === '已发布',
    batch.材料建议 != null,
  ]
  if (done[index]) return 'done'
  if (index === 0 || done[index - 1]) return 'active'
  return 'todo'
}

function statusClass(status: string): string {
  if (status === '已发布') return 'done'
  if (status === '校验失败') return 'bad'
  return 'pending'
}

function verdictClass(stake: string): string {
  const conclusions = selected.value?.发布结论?.结论明细
  if (!conclusions) return 'idle'
  const hit = conclusions.find(item => item.测点桩号 === stake)
  return hit?.结论 === '建议更换' ? 'bad' : 'ok'
}

function isWidthOver(reading: Reading): boolean {
  return typeof reading.缝宽偏差 === 'number' && Math.abs(reading.缝宽偏差) > WIDTH_TOLERANCE
}

function isAnchorOver(reading: Reading): boolean {
  const value = Number(reading.锚固偏差)
  return Number.isFinite(value) && Math.abs(value) > ANCHOR_TOLERANCE
}

function addReading() {
  importReadings.value.push({
    测点桩号: '', 缝编号: '', 实测缝宽: null, 设计缝宽: null, 锚固偏差: null,
    采集时刻: '', 采集口径: importForm.value.采集口径,
  })
}

function fillSample() {
  importForm.value = { 所属桥梁: '桥梁档案样例2', 采集日期: '2026-10-01', 采集仪器: '激光缝宽仪 LW-5', 采集口径: 'JTG/T H21 常温20℃换算' }
  importReadings.value = [
    { 测点桩号: 'K20+100', 缝编号: 'EXPA-0004', 实测缝宽: 41.5, 设计缝宽: 40, 锚固偏差: 0.9, 采集时刻: '2026-10-01 08:40', 采集口径: 'JTG/T H21 常温20℃换算' },
    { 测点桩号: 'K20+116', 缝编号: 'EXPA-0005', 实测缝宽: 58.2, 设计缝宽: 40, 锚固偏差: 7.1, 采集时刻: '2026-10-01 08:52', 采集口径: 'JTG/T H21 常温20℃换算' },
  ]
}

function syncReviewInputs() {
  const inputs: Record<string, { 复核缝宽: string | number; 复核锚固偏差: string | number; 复核结论: string }> = {}
  for (const reading of selected.value?.readings ?? []) {
    inputs[reading.测点桩号] = {
      复核缝宽: reading.复核缝宽 ?? '',
      复核锚固偏差: reading.复核锚固偏差 ?? '',
      复核结论: reading.复核结论 ?? '',
    }
  }
  reviewInputs.value = inputs
}

async function selectBatch(id: number) {
  const response = await request(`${ENDPOINT}/batches/${id}`)
  if (!response.ok) return
  selected.value = await response.json()
  syncReviewInputs()
}

async function run(action: () => Promise<Response>) {
  message.value = ''
  try {
    const response = await action()
    const payload = await response.json()
    messageOk.value = Boolean(payload.ok)
    message.value = payload.message ?? (payload.ok ? '操作完成' : '操作失败')
    if (payload.entry) {
      selected.value = payload.entry
      syncReviewInputs()
    }
    await Promise.all([reloadBatches(), reloadLedger()])
  } catch (error) {
    messageOk.value = false
    message.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function importBatch() {
  await run(() => request(`${ENDPOINT}/batches`, {
    method: 'POST',
    body: JSON.stringify({ values: { ...importForm.value, readings: importReadings.value } }),
  }))
}

async function doValidate() {
  const id = selected.value?.id
  if (!id) return
  await run(() => request(`${ENDPOINT}/batches/${id}/validate`, { method: 'POST', body: JSON.stringify({ values: {} }) }))
}

async function doPublish() {
  const id = selected.value?.id
  if (!id) return
  const reviews: Record<string, Record<string, unknown>> = {}
  for (const [stake, input] of Object.entries(reviewInputs.value)) {
    const item: Record<string, unknown> = {}
    if (input.复核缝宽 !== '') item.复核缝宽 = Number(input.复核缝宽)
    if (input.复核锚固偏差 !== '') item.复核锚固偏差 = Number(input.复核锚固偏差)
    if (input.复核结论) item.复核结论 = input.复核结论
    if (Object.keys(item).length) reviews[stake] = item
  }
  await run(() => request(`${ENDPOINT}/batches/${id}/publish`, {
    method: 'POST',
    body: JSON.stringify({ values: { ...signForm.value, 复核: reviews } }),
  }))
}

async function doSuggest() {
  const id = selected.value?.id
  if (!id) return
  await run(() => request(`${ENDPOINT}/batches/${id}/suggestions`, { method: 'POST', body: JSON.stringify({ values: {} }) }))
}

async function runLedgerAction(action: string, row: LedgerRow) {
  await run(() => request(`${ENDPOINT}/${row.id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ values: { action } }),
  }))
}

async function reloadBatches() {
  const response = await request(`${ENDPOINT}/batches?size=100`)
  if (!response.ok) return
  const payload = await response.json()
  batches.value = payload.items ?? []
}

async function reloadLedger() {
  const response = await request(`${ENDPOINT}?size=100`)
  if (!response.ok) return
  const payload = await response.json()
  ledgerRows.value = payload.items ?? []
}

onMounted(async () => {
  await Promise.all([reloadBatches(), reloadLedger()])
  const first = pendingBatches.value[0] ?? publishedBatches.value[0]
  if (first) await selectBatch(first.id)
})
</script>

<style scoped>
.step-bar { display: flex; gap: 8px; list-style: none; padding: 0; margin: 0 0 12px; }
.step-bar li { flex: 1; display: flex; align-items: center; gap: 6px; padding: 8px 10px; border: 1px solid var(--border); border-radius: 8px; background: #fff; font-size: 13px; color: var(--muted); }
.step-bar li.done { border-color: #12b76a; color: #067647; }
.step-bar li.active { border-color: var(--brand); color: var(--brand); font-weight: 600; }
.step-no { display: inline-flex; width: 20px; height: 20px; border-radius: 50%; border: 1px solid currentColor; align-items: center; justify-content: center; font-size: 12px; }
.workbench { display: flex; gap: 16px; align-items: flex-start; margin-bottom: 16px; }
.batch-panel { width: 340px; flex-shrink: 0; display: flex; flex-direction: column; gap: 10px; }
.batch-detail { flex: 1; background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; min-height: 240px; }
.import-box { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; }
.import-box summary { cursor: pointer; font-weight: 600; font-size: 13px; }
.form-item { display: block; margin-top: 8px; font-size: 12px; color: var(--muted); }
.form-item input { width: 100%; margin-top: 2px; padding: 5px 8px; border: 1px solid var(--border); border-radius: 6px; }
.reading-editor { margin-top: 10px; }
.reading-editor input { width: 100%; min-width: 72px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.import-actions { display: flex; gap: 8px; margin-top: 10px; }
.hint { color: var(--muted); font-size: 12px; margin: 8px 0 0; }
.panel-title { font-size: 13px; margin: 4px 0 0; color: var(--muted); }
.batch-list { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 6px; }
.batch-list li { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; cursor: pointer; display: flex; flex-direction: column; gap: 2px; font-size: 12px; color: var(--muted); }
.batch-list li.active { border-color: var(--brand); }
.batch-list li strong { color: #1f2937; font-size: 13px; }
.badge { align-self: flex-start; font-style: normal; font-size: 12px; border-radius: 999px; padding: 1px 8px; border: 1px solid var(--border); }
.badge.pending { color: #b54708; border-color: #f79009; }
.badge.done { color: #067647; border-color: #12b76a; }
.badge.bad { color: #b42318; border-color: #f04438; }
.detail-head { display: flex; justify-content: space-between; align-items: flex-start; }
.detail-head h3 { margin: 0; }
.section-title { font-size: 13px; margin: 14px 0 6px; }
.profile-strip { display: flex; gap: 6px; margin: 12px 0 4px; }
.profile-point { flex: 1; border: 1px solid var(--border); border-radius: 6px; padding: 6px 4px; text-align: center; display: flex; flex-direction: column; gap: 2px; background: #f8fafc; }
.profile-point.ok { border-color: #12b76a; background: #ecfdf3; }
.profile-point.bad { border-color: #f04438; background: #fef3f2; }
.profile-stake { font-size: 12px; font-weight: 600; }
.profile-joint { font-size: 12px; color: var(--muted); }
.over-limit { color: #b42318; font-weight: 600; }
.review-input { width: 100%; min-width: 88px; padding: 3px 6px; border: 1px solid var(--border); border-radius: 4px; font-size: 12px; }
.result-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; margin-top: 12px; font-size: 13px; }
.result-box.pass { border-color: #12b76a; }
.result-box.fail { border-color: #f04438; }
.result-box ul { margin: 6px 0 0; padding-left: 18px; color: #b42318; }
.result-box .data-table { margin-top: 8px; }
.sign-box { display: flex; gap: 12px; margin-top: 12px; }
.sign-box .form-item { flex: 1; margin-top: 0; }
.action-row { display: flex; gap: 10px; margin-top: 14px; }
.ok-text { color: #067647; }
</style>
