const ACTIVE_RUN_STATUSES = new Set(['queued', 'running'])

const isObject = (value) => Boolean(value) && typeof value === 'object' && !Array.isArray(value)
const runId = (run) => String(run?.run_id ?? run?.id ?? '')
const reportMarkdown = (report) => typeof report === 'string'
  ? report
  : String(report?.markdown ?? '')

export function getAiAggregationRunStatus(run) {
  return String(run?.analysis_status ?? run?.status ?? '').toLowerCase()
}

export function isAiAggregationRunActive(run) {
  return ACTIVE_RUN_STATUSES.has(getAiAggregationRunStatus(run))
}

export function getAiAggregationPollDelay(run, activePollMs = 2500) {
  return isAiAggregationRunActive(run) ? activePollMs : null
}

export function mergeAiAggregationRun(previousRun, update) {
  if (!previousRun) return update || null
  if (!update) return previousRun

  const merged = { ...previousRun, ...update }
  const previousReport = previousRun.report
  const updatedReport = update.report

  if (isObject(previousReport) && isObject(updatedReport)) {
    merged.report = { ...previousReport, ...updatedReport }
  }

  const previousMarkdown = reportMarkdown(previousReport)
  const updatedMarkdown = reportMarkdown(updatedReport)
  if (previousMarkdown && !updatedMarkdown) {
    if (isObject(merged.report)) {
      merged.report = { ...merged.report, markdown: previousMarkdown }
    } else {
      merged.report = previousReport
    }
  }

  return merged
}

export function shouldRefreshAiAggregationRunDetail(previousRun, currentRun) {
  const previousId = runId(previousRun)
  return Boolean(
    previousId
    && previousId === runId(currentRun)
    && isAiAggregationRunActive(previousRun),
  )
}
