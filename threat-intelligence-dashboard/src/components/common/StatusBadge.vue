<template>
  <span :class="badgeClass">
    <span v-if="dot" class="status-badge__dot" />
    <slot>{{ label }}</slot>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  label: {
    type: String,
    default: ''
  },
  tone: {
    type: String,
    default: 'neutral'
  },
  dot: {
    type: Boolean,
    default: true
  }
})

const badgeClass = computed(() => ['status-badge', `status-badge--${props.tone}`])
</script>

<style scoped lang="scss">
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 28px;
  padding: 0 12px;
  border: 1px solid transparent;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.02em;
  white-space: nowrap;
}

.status-badge__dot {
  width: 7px;
  height: 7px;
  border-radius: 999px;
  background: currentColor;
  opacity: 0.9;
}

.status-badge--neutral {
  color: var(--ti-text-secondary);
  background: var(--ti-panel-muted);
  border-color: var(--ti-border-soft);
}

.status-badge--primary {
  color: var(--ti-primary);
  background: rgba(45, 93, 255, 0.1);
  border-color: rgba(45, 93, 255, 0.16);
}

.status-badge--success {
  color: var(--ti-success-strong);
  background: rgba(40, 122, 79, 0.1);
  border-color: rgba(40, 122, 79, 0.16);
}

.status-badge--warning {
  color: var(--ti-warning-strong);
  background: rgba(232, 128, 48, 0.12);
  border-color: rgba(232, 128, 48, 0.16);
}

.status-badge--danger {
  color: var(--ti-danger-strong);
  background: rgba(207, 68, 50, 0.12);
  border-color: rgba(207, 68, 50, 0.16);
}
</style>
