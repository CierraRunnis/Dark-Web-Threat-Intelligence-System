<template>
  <PrototypeVueShell page-class="page-situation page-threat-situation" page-id="threat-situation-vue">
    <div class="threat-situation-host">
      <ThreatSituation />
    </div>
  </PrototypeVueShell>
</template>

<script setup>
import PrototypeVueShell from '@/components/layout/PrototypeVueShell.vue'
import ThreatSituation from '@/views/ThreatSituation.vue'
</script>

<style scoped lang="scss">
.threat-situation-host {
  min-width: 0;
  --ti-surface-default: var(--surface);
  --ti-panel-emphasis: var(--surface);
  --ti-panel-muted: var(--bg);
  --ti-border-default: var(--border);
  --ti-border-soft: var(--border);
  --ti-border-strong: color-mix(in oklch, var(--fg) 20%, var(--border));
  --ti-text-primary: var(--fg);
  --ti-text-secondary: var(--muted);
  --ti-text-muted: var(--muted);
  --ti-primary: var(--accent);
  --ti-accent-strong: var(--accent);
  --ti-success-strong: var(--success);
  --ti-warning-strong: var(--warning);
  --ti-danger-strong: var(--danger);
  --ti-shadow-card: 0 1px 2px color-mix(in oklch, var(--fg) 5%, transparent);
  --ti-shadow-card-hover: 0 3px 9px color-mix(in oklch, var(--fg) 8%, transparent);
  --ti-shadow-panel: 0 1px 2px color-mix(in oklch, var(--fg) 5%, transparent);
}

.threat-situation-host :deep(.threat-situation-page) {
  min-width: 0;
  gap: 8px;
  color: var(--fg);
}

.threat-situation-host :deep(.ti-card),
.threat-situation-host :deep(.ti-panel) {
  border: 1px solid var(--border);
  border-radius: 4px;
  background: var(--surface);
  box-shadow: 0 1px 2px color-mix(in oklch, var(--fg) 5%, transparent);
  backdrop-filter: none;
}

.threat-situation-host :deep(.ti-card:hover) {
  border-color: color-mix(in oklch, var(--fg) 18%, var(--border));
  box-shadow: 0 3px 9px color-mix(in oklch, var(--fg) 8%, transparent);
}

.threat-situation-host :deep(.executive-hero) {
  min-height: 72px;
  align-items: center;
  gap: 12px;
  padding: 12px 14px;
  border-left: 3px solid var(--danger);
}

.threat-situation-host :deep(.executive-hero__copy h2) {
  margin: 0;
  color: var(--fg);
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 650;
  letter-spacing: 0;
}

.threat-situation-host :deep(.executive-hero__copy p) {
  margin: 5px 0 0;
  color: var(--muted);
  font-size: 12px;
  line-height: 1.55;
}

.threat-situation-host :deep(.cards-grid),
.threat-situation-host :deep(.charts-grid),
.threat-situation-host :deep(.monitoring-summary-grid),
.threat-situation-host :deep(.content-grid) {
  gap: 8px;
}

.threat-situation-host :deep(.cards-grid),
.threat-situation-host :deep(.charts-grid),
.threat-situation-host :deep(.monitoring-section),
.threat-situation-host :deep(.content-grid) {
  margin-top: 0;
}

.threat-situation-host :deep(.executive-card) {
  min-height: 104px;
  padding: 12px 14px;
}

.threat-situation-host :deep(.executive-card__label) {
  color: var(--muted);
  font-size: 12px;
}

.threat-situation-host :deep(.executive-card__value) {
  margin-top: 8px;
  color: var(--fg);
  font: 750 32px/1 var(--font-mono);
}

.threat-situation-host :deep(.executive-card p) {
  margin: 9px 0 0;
  color: var(--muted);
  font-size: 11px;
}

.threat-situation-host :deep(.chart-panel) {
  min-width: 0;
  padding: 12px 12px 9px;
}

.threat-situation-host :deep(.chart-panel__header) {
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.threat-situation-host :deep(.chart-panel__eyebrow) {
  gap: 5px;
  color: var(--muted);
  font: 700 10px var(--font-mono);
  letter-spacing: 0.1em;
}

.threat-situation-host :deep(.chart-panel__title) {
  margin-top: 2px;
  color: var(--fg);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 650;
}

.threat-situation-host :deep(.chart-panel__body) {
  min-width: 0;
  padding-top: 7px;
  border-top: 1px solid var(--border);
}

.threat-situation-host :deep(.monitoring-section) {
  padding: 12px;
}

.threat-situation-host :deep(.monitoring-section__header) {
  align-items: center;
  gap: 8px;
  margin-bottom: 10px;
}

.threat-situation-host :deep(.monitoring-section__header h3) {
  margin-top: 2px;
  color: var(--fg);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 650;
}

.threat-situation-host :deep(.ti-kicker) {
  color: var(--muted);
  font: 700 10px var(--font-mono);
  letter-spacing: 0.1em;
}

.threat-situation-host :deep(.monitoring-card),
.threat-situation-host :deep(.sample-alert-item) {
  padding: 11px 12px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--bg);
}

.threat-situation-host :deep(.monitoring-card__label) {
  color: var(--muted);
  font-size: 11px;
}

.threat-situation-host :deep(.monitoring-card__value) {
  margin-top: 5px;
  color: var(--fg);
  font: 750 25px/1 var(--font-mono);
}

.threat-situation-host :deep(.monitoring-card p),
.threat-situation-host :deep(.sample-alert-item p) {
  margin-top: 7px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.5;
}

.threat-situation-host :deep(.ti-card-header) {
  min-height: 44px;
  gap: 8px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}

.threat-situation-host :deep(.ti-card-title) {
  color: var(--fg);
  font-family: var(--font-display);
  font-size: 17px;
  font-weight: 650;
}

.threat-situation-host :deep(.ti-card-body) {
  padding: 10px 12px 12px;
}

.threat-situation-host :deep(.sample-alert-list) {
  gap: 7px;
  padding-right: 4px;
}

.threat-situation-host :deep(.sample-alert-item__header strong) {
  color: var(--fg);
  font-size: 12px;
}

.threat-situation-host :deep(.sample-alert-item__header span),
.threat-situation-host :deep(.sample-links) {
  color: var(--muted);
  font-size: 11px;
}

.threat-situation-host :deep(.sample-links a) {
  color: var(--accent);
}

.threat-situation-host :deep(.status-badge) {
  min-height: 22px;
  gap: 5px;
  padding: 2px 7px;
  border-radius: 6px;
  font-size: 11px;
  font-weight: 600;
}

.threat-situation-host :deep(.el-button) {
  min-height: 32px;
  padding: 6px 10px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 650;
}

.threat-situation-host :deep(.el-button--primary) {
  --el-button-bg-color: var(--accent);
  --el-button-border-color: var(--accent);
  --el-button-hover-bg-color: color-mix(in oklch, var(--accent) 86%, black);
  --el-button-hover-border-color: color-mix(in oklch, var(--accent) 86%, black);
}

.threat-situation-host :deep(.ti-table-shell) {
  border: 1px solid var(--border);
  border-radius: 3px;
}

.threat-situation-host :deep(.el-table) {
  --el-table-border-color: var(--border);
  --el-table-header-bg-color: var(--bg);
  --el-table-row-hover-bg-color: var(--fg-soft);
  --el-table-current-row-bg-color: var(--fg-soft);
  --el-table-bg-color: var(--surface);
  --el-table-tr-bg-color: var(--surface);
  color: var(--fg);
  font-size: 11px;
}

.threat-situation-host :deep(.el-table th.el-table__cell) {
  background: var(--bg);
  color: var(--muted);
  font: 700 10px var(--font-mono);
  letter-spacing: 0.05em;
}

.threat-situation-host :deep(.el-table .el-table__cell) {
  padding: 8px 0;
  border-bottom-color: var(--border);
}

.threat-situation-host :deep(.el-table__inner-wrapper::before),
.threat-situation-host :deep(.el-table--border::after),
.threat-situation-host :deep(.el-table--border::before) {
  background-color: var(--border);
}

@media (max-width: 1280px) {
  .threat-situation-host :deep(.cards-grid),
  .threat-situation-host :deep(.monitoring-summary-grid) {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .threat-situation-host :deep(.charts-grid),
  .threat-situation-host :deep(.content-grid) {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 900px) {
  .threat-situation-host :deep(.cards-grid),
  .threat-situation-host :deep(.monitoring-summary-grid) {
    grid-template-columns: 1fr;
  }

  .threat-situation-host :deep(.executive-hero),
  .threat-situation-host :deep(.monitoring-section__header) {
    align-items: stretch;
  }
}
</style>
