<template>
  <section class="chart-panel ti-card ti-reveal-up">
    <header class="chart-panel__header">
      <div>
        <div class="chart-panel__eyebrow">
          <el-icon v-if="icon"><component :is="icon" /></el-icon>
          <span>{{ eyebrow }}</span>
        </div>
        <h3 class="chart-panel__title">{{ title }}</h3>
      </div>
      <div v-if="$slots.actions" class="chart-panel__actions">
        <slot name="actions" />
      </div>
    </header>
    <div class="chart-panel__body" :style="{ minHeight: height, height }">
      <slot />
    </div>
  </section>
</template>

<script setup>
defineProps({
  eyebrow: {
    type: String,
    default: '图表'
  },
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  },
  icon: {
    type: String,
    default: ''
  },
  height: {
    type: String,
    default: '280px'
  }
})
</script>

<style scoped lang="scss">
.chart-panel {
  padding: 18px 18px 10px;
}

.chart-panel__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: flex-start;
  margin-bottom: 14px;
}

.chart-panel__eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--ti-text-muted);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.chart-panel__title {
  margin: 6px 0 0;
  color: var(--ti-text-primary);
  font-size: 18px;
  line-height: 1.3;
}

.chart-panel__body {
  position: relative;
}

@media (max-width: 768px) {
  .chart-panel__header {
    flex-direction: column;
  }
}
</style>
