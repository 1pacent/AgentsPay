<template>
  <div class="eco-container">
    <!-- Navbar -->
    <nav class="eco-nav">
      <div class="nav-brand">
        <router-link to="/" class="back-link">← HOME</router-link>
        <span class="nav-sep">|</span>
        <span class="nav-title">AGENT ECO SIMULATOR</span>
      </div>
      <div class="nav-badge">
        <span :class="['health-dot', apiOk ? 'ok' : 'err']">■</span>
        {{ apiOk ? 'API ONLINE' : 'API OFFLINE' }}
      </div>
    </nav>

    <div class="eco-body">
      <!-- ── LEFT COLUMN: launcher ── -->
      <aside class="launcher-col">
        <div class="panel">
          <div class="panel-header">◇ NEW RUN</div>

          <div class="field-group">
            <label class="field-label">Scenario</label>
            <select v-model="form.scenario_id" class="eco-select" :disabled="launching">
              <option value="" disabled>Select scenario…</option>
              <option v-for="s in scenarios" :key="s.id" :value="s.id">
                {{ s.name }}
              </option>
            </select>
            <p v-if="selectedScenario" class="field-hint">{{ selectedScenario.description }}</p>
            <p v-if="selectedScenario?.test_question" class="field-question">
              ❓ {{ selectedScenario.test_question }}
            </p>
          </div>

          <div class="field-group">
            <label class="field-label">Ticks</label>
            <input v-model.number="form.ticks" type="number" min="10" max="500" step="10" class="eco-input" :disabled="launching" />
          </div>

          <div class="field-group">
            <label class="field-label">AgentPays Fee %</label>
            <input v-model.number="form.fee_pct" type="number" min="0" max="0.05" step="0.001" class="eco-input" :disabled="launching" />
          </div>

          <div class="field-group">
            <label class="field-label">Reputation Algorithm</label>
            <select v-model="form.reputation_algorithm" class="eco-select" :disabled="launching">
              <option value="time_decayed">Time Decayed</option>
              <option value="star_rating">Star Rating</option>
              <option value="completion_rate">Completion Rate</option>
              <option value="verified_delivery">Verified Delivery</option>
            </select>
          </div>

          <div class="field-group">
            <label class="field-label">Deliverable Validator</label>
            <select v-model="form.validator" class="eco-select" :disabled="launching">
              <option value="deterministic">Deterministic</option>
              <option value="length_heuristic">Length Heuristic</option>
              <option value="always_pass">Always Pass</option>
              <option value="always_fail">Always Fail</option>
            </select>
          </div>

          <button
            class="launch-btn"
            :disabled="!form.scenario_id || launching"
            @click="launchRun"
          >
            <span v-if="launching">LAUNCHING…</span>
            <span v-else>LAUNCH RUN →</span>
          </button>

          <div v-if="launchError" class="error-msg">{{ launchError }}</div>
        </div>

        <!-- Compare panel -->
        <div class="panel" style="margin-top: 20px;">
          <div class="panel-header">◇ COMPARE RUNS</div>
          <p class="field-hint">Select ≥2 completed runs from the table, then compare.</p>
          <div class="selected-runs-list">
            <div
              v-for="rid in compareSelection"
              :key="rid"
              class="compare-chip"
            >
              {{ rid }}
              <button class="chip-remove" @click="removeFromCompare(rid)">×</button>
            </div>
            <p v-if="compareSelection.length === 0" class="field-hint" style="margin:0">None selected</p>
          </div>
          <button
            class="compare-btn"
            :disabled="compareSelection.length < 2 || comparing"
            @click="runComparison"
          >
            {{ comparing ? 'COMPARING…' : 'COMPARE →' }}
          </button>
        </div>
      </aside>

      <!-- ── RIGHT COLUMN: live run + history ── -->
      <main class="main-col">

        <!-- Active run card -->
        <div v-if="activeRun" class="panel active-run-panel">
          <div class="panel-header">
            ■ ACTIVE RUN — {{ activeRun.run_id }}
            <span :class="['status-badge', activeRun.status]">{{ activeRun.status.toUpperCase() }}</span>
          </div>

          <div v-if="activeRun.status === 'running' || activeRun.status === 'starting'" class="run-progress">
            <div class="progress-bar">
              <div class="progress-fill" :style="{ width: progressPct + '%' }"></div>
            </div>
            <span class="progress-label">{{ activeRun.status }}</span>
          </div>

          <div v-if="activeRun.status === 'error'" class="error-msg">
            {{ activeRun.error }}
          </div>

          <div v-if="activeRun.status === 'complete' && activeRun.result" class="metrics-grid">
            <MetricCard label="AEHS" :value="fmt4(activeRun.result.metrics?.aehs)" accent />
            <MetricCard label="Completion Rate" :value="fmtPct(activeRun.result.metrics?.completion_rate)" />
            <MetricCard label="GTV (USDC)" :value="fmt4(activeRun.result.metrics?.gross_transaction_value_usdc)" />
            <MetricCard label="Dispute Rate" :value="fmtPct(activeRun.result.metrics?.dispute_rate)" warn />
            <MetricCard label="Avg Quality" :value="fmt4(activeRun.result.metrics?.average_quality)" />
            <MetricCard label="Fee Revenue" :value="fmt4(activeRun.result.metrics?.agentpays_fee_revenue_usdc)" />
            <MetricCard label="Seller HHI" :value="fmt4(activeRun.result.metrics?.seller_concentration_hhi)" />
            <MetricCard label="Ticks Run" :value="activeRun.result.ticks_run" />
          </div>
        </div>

        <!-- Comparison result -->
        <div v-if="comparisonTable" class="panel">
          <div class="panel-header">◇ COMPARISON RESULT</div>
          <pre class="comparison-md">{{ comparisonTable }}</pre>
          <button class="clear-btn" @click="comparisonTable = null">CLEAR</button>
        </div>

        <!-- Run history -->
        <div class="panel">
          <div class="panel-header" style="display:flex;justify-content:space-between;align-items:center;">
            <span>◇ RUN HISTORY</span>
            <button class="refresh-btn" @click="fetchRuns">↻ REFRESH</button>
          </div>

          <div v-if="runs.length === 0" class="empty-state">No runs yet. Launch one →</div>

          <table v-else class="runs-table">
            <thead>
              <tr>
                <th></th>
                <th>Run ID</th>
                <th>Scenario</th>
                <th>Status</th>
                <th>AEHS</th>
                <th>Completion</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              <tr
                v-for="run in runs"
                :key="run.run_id"
                :class="{ 'active-row': activeRun?.run_id === run.run_id }"
              >
                <td>
                  <input
                    type="checkbox"
                    :checked="compareSelection.includes(run.run_id)"
                    :disabled="run.status !== 'complete'"
                    @change="toggleCompare(run.run_id)"
                  />
                </td>
                <td class="mono-cell">{{ run.run_id }}</td>
                <td>{{ run.scenario_id }}</td>
                <td><span :class="['status-badge', run.status]">{{ run.status }}</span></td>
                <td class="mono-cell">{{ run.aehs != null ? fmt4(run.aehs) : '—' }}</td>
                <td class="mono-cell">{{ run.completion_rate != null ? fmtPct(run.completion_rate) : '—' }}</td>
                <td>
                  <button
                    v-if="run.status === 'complete'"
                    class="action-btn"
                    @click="viewRun(run.run_id)"
                  >VIEW</button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>

      </main>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount } from 'vue'
import {
  listScenarios, startRun, getRun, listRuns, compareRuns, ecoHealth
} from '../api/eco.js'

// ── state ──────────────────────────────────────────────────────────────────
const scenarios = ref([])
const runs = ref([])
const apiOk = ref(false)
const launching = ref(false)
const launchError = ref(null)
const activeRun = ref(null)
const compareSelection = ref([])
const comparing = ref(false)
const comparisonTable = ref(null)
let pollTimer = null

const form = ref({
  scenario_id: '',
  ticks: 100,
  fee_pct: 0.005,
  reputation_algorithm: 'time_decayed',
  validator: 'deterministic',
})

// ── computed ────────────────────────────────────────────────────────────────
const selectedScenario = computed(() =>
  scenarios.value.find(s => s.id === form.value.scenario_id) || null
)

const progressPct = computed(() => {
  if (!activeRun.value) return 0
  if (activeRun.value.status === 'starting') return 5
  if (activeRun.value.status === 'running') return 50
  if (activeRun.value.status === 'complete') return 100
  return 0
})

// ── formatters ──────────────────────────────────────────────────────────────
const fmt4 = v => (v != null ? Number(v).toFixed(4) : '—')
const fmtPct = v => (v != null ? (Number(v) * 100).toFixed(1) + '%' : '—')

// ── lifecycle ───────────────────────────────────────────────────────────────
onMounted(async () => {
  await Promise.all([checkHealth(), fetchScenarios(), fetchRuns()])
})

onBeforeUnmount(() => clearPoll())

// ── methods ─────────────────────────────────────────────────────────────────
async function checkHealth() {
  try {
    await ecoHealth()
    apiOk.value = true
  } catch {
    apiOk.value = false
  }
}

async function fetchScenarios() {
  try {
    const data = await listScenarios()
    scenarios.value = data.scenarios || []
  } catch (e) {
    console.error('fetchScenarios', e)
  }
}

async function fetchRuns() {
  try {
    const data = await listRuns()
    runs.value = (data.runs || []).slice().reverse()
  } catch (e) {
    console.error('fetchRuns', e)
  }
}

async function launchRun() {
  launchError.value = null
  launching.value = true
  try {
    const data = await startRun({
      scenario_id: form.value.scenario_id,
      ticks: form.value.ticks,
      fee_pct: form.value.fee_pct,
      reputation_algorithm: form.value.reputation_algorithm,
      validator: form.value.validator,
    })
    activeRun.value = { run_id: data.run_id, status: data.status }
    startPoll(data.run_id)
    await fetchRuns()
  } catch (e) {
    launchError.value = e.message || 'Launch failed'
  } finally {
    launching.value = false
  }
}

function startPoll(runId) {
  clearPoll()
  pollTimer = setInterval(async () => {
    try {
      const data = await getRun(runId)
      activeRun.value = data
      // Refresh runs list on completion
      if (data.status === 'complete' || data.status === 'error') {
        clearPoll()
        await fetchRuns()
      }
    } catch (e) {
      console.error('poll', e)
    }
  }, 2000)
}

function clearPoll() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

async function viewRun(runId) {
  try {
    const data = await getRun(runId)
    activeRun.value = data
  } catch (e) {
    console.error('viewRun', e)
  }
}

function toggleCompare(runId) {
  const idx = compareSelection.value.indexOf(runId)
  if (idx === -1) compareSelection.value.push(runId)
  else compareSelection.value.splice(idx, 1)
}

function removeFromCompare(runId) {
  compareSelection.value = compareSelection.value.filter(r => r !== runId)
}

async function runComparison() {
  comparing.value = true
  comparisonTable.value = null
  try {
    const data = await compareRuns(compareSelection.value)
    comparisonTable.value = data.comparison_table
  } catch (e) {
    comparisonTable.value = `Error: ${e.message}`
  } finally {
    comparing.value = false
  }
}
</script>

<!-- Inline sub-component for metric cards -->
<script>
export const MetricCard = {
  props: { label: String, value: [String, Number], accent: Boolean, warn: Boolean },
  template: `
    <div class="metric-card" :class="{ accent, warn }">
      <div class="metric-value">{{ value ?? '—' }}</div>
      <div class="metric-label">{{ label }}</div>
    </div>
  `
}
</script>

<style scoped>
/* ── Layout ── */
.eco-container { min-height: 100vh; background: #fafafa; font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif; }

.eco-nav {
  height: 60px; background: #000; color: #fff;
  display: flex; align-items: center; justify-content: space-between;
  padding: 0 40px;
}
.nav-brand { display: flex; align-items: center; gap: 16px; font-family: 'JetBrains Mono', monospace; font-size: 0.9rem; font-weight: 700; }
.back-link { color: #FF4500; text-decoration: none; letter-spacing: 1px; }
.nav-sep { color: #444; }
.nav-title { color: #fff; letter-spacing: 2px; }
.nav-badge { font-family: 'JetBrains Mono', monospace; font-size: 0.75rem; display: flex; align-items: center; gap: 6px; color: #aaa; }
.health-dot { font-size: 0.6rem; }
.health-dot.ok { color: #00ff88; }
.health-dot.err { color: #ff4444; }

.eco-body { display: flex; gap: 24px; padding: 28px 40px; max-width: 1400px; margin: 0 auto; }

.launcher-col { width: 320px; flex-shrink: 0; }
.main-col { flex: 1; display: flex; flex-direction: column; gap: 20px; }

/* ── Panel ── */
.panel {
  background: #fff; border: 1px solid #e5e5e5;
  padding: 24px;
}
.panel-header {
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.75rem; font-weight: 700; letter-spacing: 2px;
  color: #000; margin-bottom: 20px;
  display: flex; align-items: center; gap: 10px;
}
.active-run-panel { border-left: 3px solid #FF4500; }

/* ── Form ── */
.field-group { margin-bottom: 16px; }
.field-label {
  display: block;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.7rem; font-weight: 700; letter-spacing: 1px;
  color: #666; margin-bottom: 6px; text-transform: uppercase;
}
.field-hint { font-size: 0.8rem; color: #999; margin: 6px 0 0; line-height: 1.5; }
.field-question { font-size: 0.8rem; color: #FF4500; margin: 8px 0 0; line-height: 1.5; font-style: italic; }

.eco-select, .eco-input {
  width: 100%; padding: 8px 10px;
  border: 1px solid #e5e5e5; background: #fafafa;
  font-family: 'JetBrains Mono', monospace; font-size: 0.85rem;
  color: #000; outline: none; box-sizing: border-box;
  appearance: none;
}
.eco-select:focus, .eco-input:focus { border-color: #000; }
.eco-select:disabled, .eco-input:disabled { opacity: 0.5; }

/* ── Buttons ── */
.launch-btn {
  width: 100%; padding: 12px;
  background: #000; color: #fff;
  border: none; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; font-size: 0.85rem; font-weight: 700; letter-spacing: 1px;
  margin-top: 8px; transition: background 0.15s;
}
.launch-btn:hover:not(:disabled) { background: #FF4500; }
.launch-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.compare-btn {
  width: 100%; padding: 10px;
  background: transparent; color: #000;
  border: 1px solid #000; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; font-weight: 700; letter-spacing: 1px;
  margin-top: 12px; transition: all 0.15s;
}
.compare-btn:hover:not(:disabled) { background: #000; color: #fff; }
.compare-btn:disabled { opacity: 0.4; cursor: not-allowed; }

.refresh-btn {
  background: transparent; border: 1px solid #e5e5e5; padding: 4px 10px;
  font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; cursor: pointer; color: #666;
}
.refresh-btn:hover { border-color: #000; color: #000; }

.action-btn {
  padding: 4px 10px;
  background: transparent; border: 1px solid #000; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; font-weight: 700;
  transition: all 0.15s;
}
.action-btn:hover { background: #000; color: #fff; }

.clear-btn {
  margin-top: 12px; padding: 6px 14px;
  background: transparent; border: 1px solid #e5e5e5; cursor: pointer;
  font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: #999;
}

/* ── Status badges ── */
.status-badge {
  font-family: 'JetBrains Mono', monospace; font-size: 0.65rem; font-weight: 700;
  padding: 2px 8px; letter-spacing: 1px;
}
.status-badge.starting { background: #fff3cd; color: #856404; }
.status-badge.running { background: #cce5ff; color: #004085; }
.status-badge.complete { background: #d4edda; color: #155724; }
.status-badge.error { background: #f8d7da; color: #721c24; }

/* ── Progress ── */
.run-progress { margin: 16px 0; }
.progress-bar { height: 4px; background: #f0f0f0; width: 100%; }
.progress-fill { height: 100%; background: #FF4500; transition: width 0.5s; }
.progress-label { font-family: 'JetBrains Mono', monospace; font-size: 0.7rem; color: #999; margin-top: 6px; display: block; }

/* ── Metrics grid ── */
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px; margin-top: 16px;
}
.metric-card {
  border: 1px solid #e5e5e5; padding: 14px 12px;
  background: #fafafa;
}
.metric-card.accent { border-color: #FF4500; background: #fff8f5; }
.metric-card.warn { border-color: #ffc107; background: #fffdf0; }
.metric-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 1.25rem; font-weight: 700; color: #000; margin-bottom: 4px;
}
.metric-card.accent .metric-value { color: #FF4500; }
.metric-label { font-size: 0.7rem; color: #999; text-transform: uppercase; letter-spacing: 1px; }

/* ── Comparison ── */
.comparison-md {
  font-family: 'JetBrains Mono', monospace; font-size: 0.8rem;
  white-space: pre; overflow-x: auto; line-height: 1.6;
  background: #f8f8f8; padding: 16px; border: 1px solid #e5e5e5;
  margin-top: 8px;
}

/* ── Compare chips ── */
.selected-runs-list { display: flex; flex-wrap: wrap; gap: 6px; margin: 8px 0; min-height: 28px; }
.compare-chip {
  display: flex; align-items: center; gap: 4px;
  background: #000; color: #fff; padding: 3px 8px;
  font-family: 'JetBrains Mono', monospace; font-size: 0.7rem;
}
.chip-remove { background: none; border: none; color: #FF4500; cursor: pointer; font-size: 1rem; line-height: 1; padding: 0 2px; }

/* ── Table ── */
.runs-table { width: 100%; border-collapse: collapse; font-size: 0.85rem; margin-top: 8px; }
.runs-table th {
  text-align: left; padding: 8px 10px;
  font-family: 'JetBrains Mono', monospace; font-size: 0.65rem;
  font-weight: 700; letter-spacing: 1px; color: #999; text-transform: uppercase;
  border-bottom: 2px solid #000;
}
.runs-table td { padding: 10px; border-bottom: 1px solid #f0f0f0; vertical-align: middle; }
.runs-table .active-row td { background: #fff8f5; }
.mono-cell { font-family: 'JetBrains Mono', monospace; font-size: 0.8rem; }

/* ── Misc ── */
.error-msg { color: #dc3545; font-size: 0.8rem; margin-top: 8px; font-family: 'JetBrains Mono', monospace; }
.empty-state { color: #999; font-size: 0.85rem; padding: 20px 0; text-align: center; }

@media (max-width: 900px) {
  .eco-body { flex-direction: column; }
  .launcher-col { width: 100%; }
  .metrics-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
