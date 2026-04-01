<template>
  <div class="section-header">
    <div class="section-header__main">
      <span v-if="eyebrow" class="section-header__eyebrow">{{ eyebrow }}</span>
      <h2 class="section-header__title">{{ title }}</h2>
      <p v-if="description" class="section-header__description">{{ description }}</p>
    </div>
    <div v-if="$slots.actions || meta?.length" class="section-header__aside">
      <div v-if="meta?.length" class="section-header__meta">
        <span v-for="item in meta" :key="`${item.label}-${item.value}`" class="section-header__meta-item">
          <span class="section-header__meta-label">{{ item.label }}</span>
          <span class="section-header__meta-value">{{ item.value }}</span>
        </span>
      </div>
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup>
defineProps({
  eyebrow: {
    type: String,
    default: ''
  },
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  },
  meta: {
    type: Array,
    default: () => []
  }
})
</script>

<style scoped lang="scss">
.section-header {
  display: flex;
  justify-content: space-between;
  gap: 20px;
  align-items: flex-end;
}

.section-header__main {
  max-width: 760px;
}

.section-header__eyebrow {
  display: inline-block;
  margin-bottom: 8px;
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.14em;
  text-transform: uppercase;
}

.section-header__title {
  margin: 0;
  font-size: clamp(26px, 2.8vw, 38px);
  line-height: 1.05;
  letter-spacing: -0.03em;
  color: var(--ti-text-primary);
}

.section-header__description {
  margin: 10px 0 0;
  max-width: 720px;
  color: var(--ti-text-secondary);
  font-size: 14px;
  line-height: 1.7;
}

.section-header__aside {
  display: flex;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.section-header__meta {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 10px;
}

.section-header__meta-item {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.75);
  color: var(--ti-text-secondary);
  font-size: 12px;
}

.section-header__meta-label {
  color: var(--ti-text-muted);
}

.section-header__meta-value {
  color: var(--ti-text-primary);
  font-weight: 600;
}

@media (max-width: 1024px) {
  .section-header {
    flex-direction: column;
    align-items: stretch;
  }

  .section-header__aside {
    justify-content: flex-start;
  }

  .section-header__meta {
    justify-content: flex-start;
  }
}
</style>
