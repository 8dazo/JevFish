<template>
  <aside v-if="visible" class="router-panel">
    <div class="router-head">
      <div>
        <div class="eyebrow">COGNITIVE ROUTER</div>
        <div class="title-row">
          <span class="pulse" :class="statusTone"></span>
          <strong>JevFish live</strong>
        </div>
      </div>
      <span class="mode">{{ metrics?.decision_engine || 'hybrid' }}</span>
    </div>

    <div v-if="metrics" class="metric-grid">
      <div class="metric primary">
        <span class="value">{{ metrics.system_one_share_pct }}%</span>
        <span class="label">turns kept in System One</span>
      </div>
      <div class="metric">
        <span class="value">{{ metrics.jev_calls }}</span>
        <span class="label">Jev decisions</span>
      </div>
      <div class="metric">
        <span class="value">{{ metrics.llm_fallbacks }}</span>
        <span class="label">full LLM fallbacks</span>
      </div>
      <div class="metric">
        <span class="value">{{ metrics.system_two_requests }}</span>
        <span class="label">System Two requests</span>
      </div>
      <div class="metric">
        <span class="value">{{ metrics.observation_posts }}</span>
        <span class="label">personalized observations</span>
      </div>
      <div class="metric">
        <span class="value">{{ metrics.errors + metrics.observation_errors }}</span>
        <span class="label">routing / observation errors</span>
      </div>
    </div>

    <div v-else class="waiting">
      Waiting for the first Jev decision…
    </div>

    <div class="router-foot">
      <span>{{ metrics?.jev_model || 'jev-latest' }}</span>
      <span>{{ metrics?.observation_mode || 'oasis_refresh' }}</span>
      <span>{{ metrics?.runner_status || 'starting' }}</span>
    </div>
  </aside>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { getSimulationMetrics } from '../api/system'

const route = useRoute()
const metrics = ref(null)
let timer = null

const simulationId = computed(() => route.params.simulationId)
const visible = computed(() => route.name === 'SimulationRun' && Boolean(simulationId.value))
const statusTone = computed(() => {
  const status = metrics.value?.runner_status
  if (status === 'failed') return 'bad'
  if (status === 'completed' || status === 'stopped') return 'done'
  return 'live'
})

const load = async () => {
  if (!visible.value) return
  try {
    const response = await getSimulationMetrics(simulationId.value)
    if (response?.success) metrics.value = response.data
  } catch (error) {
    // Metric files do not exist until the simulation runtime starts writing them.
    if (error?.response?.status !== 404) {
      console.debug('JevFish metrics unavailable:', error?.message)
    }
  }
}

const stop = () => {
  if (timer) {
    clearInterval(timer)
    timer = null
  }
}

const start = () => {
  stop()
  if (!visible.value) return
  load()
  timer = setInterval(load, 3000)
}

watch([visible, simulationId], start, { immediate: true })
onBeforeUnmount(stop)
</script>

<style scoped>
.router-panel {
  position: fixed;
  right: 18px;
  bottom: 18px;
  z-index: 999;
  width: min(380px, calc(100vw - 36px));
  border: 1px solid #111;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 6px 6px 0 #111;
  padding: 14px;
  backdrop-filter: blur(8px);
  font-family: 'JetBrains Mono', monospace;
}

.router-head,
.router-foot,
.title-row {
  display: flex;
  align-items: center;
}

.router-head {
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 12px;
}

.eyebrow {
  font-size: 9px;
  letter-spacing: 0.14em;
  color: #777;
  margin-bottom: 4px;
}

.title-row {
  gap: 7px;
  font-size: 13px;
}

.mode {
  border: 1px solid #111;
  padding: 3px 6px;
  font-size: 9px;
  text-transform: uppercase;
}

.pulse {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #111;
}

.pulse.live { animation: pulse 1.4s infinite; }
.pulse.done { opacity: 0.45; }
.pulse.bad { border-radius: 0; transform: rotate(45deg); }

.metric-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  border-top: 1px solid #ddd;
  border-left: 1px solid #ddd;
}

.metric {
  min-height: 68px;
  padding: 9px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  border-right: 1px solid #ddd;
  border-bottom: 1px solid #ddd;
}

.metric.primary {
  grid-column: span 2;
  min-height: 76px;
}

.value {
  font-size: 20px;
  font-weight: 800;
  line-height: 1;
}

.primary .value { font-size: 28px; }

.label {
  font-size: 9px;
  color: #666;
  line-height: 1.25;
}

.waiting {
  padding: 20px 8px;
  border-top: 1px solid #ddd;
  border-bottom: 1px solid #ddd;
  font-size: 10px;
  color: #666;
}

.router-foot {
  justify-content: space-between;
  gap: 8px;
  margin-top: 10px;
  font-size: 8px;
  color: #777;
}

@keyframes pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.35; transform: scale(0.75); }
}

@media (max-width: 720px) {
  .router-panel {
    right: 10px;
    bottom: 10px;
    width: calc(100vw - 20px);
  }
}
</style>
