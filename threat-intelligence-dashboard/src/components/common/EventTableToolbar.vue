<template>
  <div class="event-table-toolbar">
    <div class="event-table-toolbar__heading">
      <div class="event-table-toolbar__eyebrow">{{ eyebrow }}</div>
      <h3 class="event-table-toolbar__title">{{ title }}</h3>
      <p v-if="description" class="event-table-toolbar__description">{{ description }}</p>
    </div>

    <div class="event-table-toolbar__controls">
      <div class="event-table-toolbar__filters">
        <slot name="filters" />
      </div>
      <el-input
        v-if="searchPlaceholder"
        :model-value="searchValue"
        :placeholder="searchPlaceholder"
        class="event-table-toolbar__search"
        clearable
        @update:model-value="$emit('update:searchValue', $event)"
      >
        <template #prefix>
          <el-icon><Search /></el-icon>
        </template>
      </el-input>
      <slot name="actions" />
    </div>

    <div v-if="activeFilters?.length" class="event-table-toolbar__status-bar">
      <span class="event-table-toolbar__status-label">筛选状态</span>
      <StatusBadge
        v-for="item in activeFilters"
        :key="item"
        :label="item"
        tone="neutral"
        :dot="false"
      />
    </div>
  </div>
</template>

<script setup>
import StatusBadge from '@/components/common/StatusBadge.vue'

defineProps({
  eyebrow: {
    type: String,
    default: '事件列表'
  },
  title: {
    type: String,
    required: true
  },
  description: {
    type: String,
    default: ''
  },
  searchValue: {
    type: String,
    default: ''
  },
  searchPlaceholder: {
    type: String,
    default: ''
  },
  activeFilters: {
    type: Array,
    default: () => []
  }
})

defineEmits(['update:searchValue'])
</script>

<style scoped lang="scss">
.event-table-toolbar {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.event-table-toolbar__heading {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.event-table-toolbar__eyebrow {
  color: var(--ti-accent-strong);
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
}

.event-table-toolbar__title {
  margin: 0;
  color: var(--ti-text-primary);
  font-size: 20px;
}

.event-table-toolbar__description {
  margin: 0;
  color: var(--ti-text-secondary);
  font-size: 13px;
  line-height: 1.7;
}

.event-table-toolbar__controls {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  justify-content: space-between;
}

.event-table-toolbar__filters {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  flex: 1;
}

.event-table-toolbar__search {
  width: min(280px, 100%);
}

.event-table-toolbar__status-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
  padding: 10px 12px;
  border: 1px solid var(--ti-border-soft);
  border-radius: 16px;
  background: var(--ti-panel-muted);
}

.event-table-toolbar__status-label {
  color: var(--ti-text-muted);
  font-size: 12px;
  font-weight: 600;
}

@media (max-width: 768px) {
  .event-table-toolbar__controls {
    align-items: stretch;
  }

  .event-table-toolbar__search {
    width: 100%;
  }
}
</style>
