<template>
  <article :class="cardClass">
    <div class="module-summary-card__top">
      <div class="module-summary-card__icon-wrap">
        <el-icon class="module-summary-card__icon">
          <component :is="icon" />
        </el-icon>
      </div>
      <StatusBadge v-if="trend" :label="trend" :tone="tone" :dot="false" />
    </div>
    <div class="module-summary-card__label">{{ label }}</div>
    <div class="module-summary-card__value">{{ value }}</div>
    <p class="module-summary-card__description">{{ description }}</p>
  </article>
</template>

<script setup>
import { computed } from 'vue'
import StatusBadge from '@/components/common/StatusBadge.vue'

const props = defineProps({
  label: {
    type: String,
    required: true
  },
  value: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  },
  trend: {
    type: String,
    default: ''
  },
  tone: {
    type: String,
    default: 'primary'
  },
  icon: {
    type: String,
    default: 'DataLine'
  }
})

const cardClass = computed(() => ['module-summary-card', `module-summary-card--${props.tone}`])
</script>

<style scoped lang="scss">
.module-summary-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 182px;
  padding: 22px;
  border-radius: 22px;
  border: 1px solid var(--ti-border-default);
  background: linear-gradient(180deg, rgba(255, 255, 255, 1), rgba(248, 251, 255, 0.96));
  box-shadow: var(--ti-shadow-card);
  transition:
    transform 0.24s ease,
    box-shadow 0.24s ease,
    border-color 0.24s ease;
}

.module-summary-card:hover {
  transform: translateY(-3px);
  box-shadow: var(--ti-shadow-card-hover);
}

.module-summary-card__top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
}

.module-summary-card__icon-wrap {
  display: inline-flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.88);
  border: 1px solid rgba(255, 255, 255, 0.7);
}

.module-summary-card__icon {
  font-size: 20px;
}

.module-summary-card__label {
  color: var(--ti-text-secondary);
  font-size: 13px;
  font-weight: 600;
}

.module-summary-card__value {
  font-size: clamp(30px, 3vw, 42px);
  line-height: 1;
  letter-spacing: -0.04em;
  color: var(--ti-text-primary);
  font-weight: 700;
}

.module-summary-card__description {
  margin: 0;
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.module-summary-card--primary .module-summary-card__icon {
  color: var(--ti-primary);
}

.module-summary-card--warning .module-summary-card__icon {
  color: var(--ti-warning-strong);
}

.module-summary-card--danger .module-summary-card__icon {
  color: var(--ti-danger-strong);
}

.module-summary-card--success .module-summary-card__icon {
  color: var(--ti-success-strong);
}
</style>
