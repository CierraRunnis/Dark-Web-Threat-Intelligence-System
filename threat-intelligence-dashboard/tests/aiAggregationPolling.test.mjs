import test from 'node:test'
import assert from 'node:assert/strict'

import {
  getAiAggregationPollDelay,
  mergeAiAggregationRun,
  shouldRefreshAiAggregationRunDetail,
} from '../src/prototype/aiAggregationPolling.js'

test('polls only while the selected AI report is queued or running', () => {
  assert.equal(getAiAggregationPollDelay({ analysis_status: 'queued' }), 2500)
  assert.equal(getAiAggregationPollDelay({ status: 'running' }, 800), 800)
  assert.equal(getAiAggregationPollDelay({ analysis_status: 'succeeded' }), null)
  assert.equal(getAiAggregationPollDelay({ analysis_status: 'failed' }), null)
  assert.equal(getAiAggregationPollDelay(null), null)
})

test('a run-list summary does not overwrite loaded report markdown', () => {
  const detail = {
    run_id: 'run-1',
    analysis_status: 'succeeded',
    report: {
      markdown: '# Full report\n\nBody',
      generated_at: '2026-09-04T01:00:00Z',
    },
  }
  const summary = {
    run_id: 'run-1',
    analysis_status: 'succeeded',
    delivery_status: 'succeeded',
    report: {
      excerpt: 'Report excerpt',
      generated_at: '2026-09-04T01:00:01Z',
    },
  }

  assert.deepEqual(mergeAiAggregationRun(detail, summary), {
    run_id: 'run-1',
    analysis_status: 'succeeded',
    delivery_status: 'succeeded',
    report: {
      markdown: '# Full report\n\nBody',
      excerpt: 'Report excerpt',
      generated_at: '2026-09-04T01:00:01Z',
    },
  })
})

test('a poll that began while running fetches final detail once', () => {
  assert.equal(
    shouldRefreshAiAggregationRunDetail(
      { run_id: 'run-1', analysis_status: 'running' },
      { run_id: 'run-1', analysis_status: 'succeeded' },
    ),
    true,
  )
  assert.equal(
    shouldRefreshAiAggregationRunDetail(
      { run_id: 'run-1', analysis_status: 'succeeded' },
      { run_id: 'run-1', analysis_status: 'succeeded' },
    ),
    false,
  )
  assert.equal(
    shouldRefreshAiAggregationRunDetail(
      { run_id: 'run-1', analysis_status: 'running' },
      { run_id: 'run-2', analysis_status: 'running' },
    ),
    false,
  )
})
