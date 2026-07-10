<template>
  <span>{{ displayValue }}</span>
</template>

<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  value: { type: [Number, String], default: 0 },
  duration: { type: Number, default: 720 },
  delay: { type: Number, default: 0 },
})

const displayValue = ref(String(props.value ?? 0))
let animationFrame = 0
let delayTimer = 0

function parseValue(value) {
  const text = String(value ?? 0)
  const match = text.match(/-?[\d,]+(?:\.\d+)?/)
  if (!match) return null
  const number = Number(match[0].replaceAll(',', ''))
  if (!Number.isFinite(number)) return null
  return {
    number,
    prefix: text.slice(0, match.index),
    suffix: text.slice((match.index || 0) + match[0].length),
    decimals: match[0].includes('.') ? match[0].split('.')[1].length : 0,
    grouped: match[0].includes(','),
  }
}

function formatValue(parsed, value) {
  const numeric = parsed.decimals ? value.toFixed(parsed.decimals) : String(Math.round(value))
  const formatted = parsed.grouped
    ? Number(numeric).toLocaleString('zh-CN', {
        minimumFractionDigits: parsed.decimals,
        maximumFractionDigits: parsed.decimals,
      })
    : numeric
  return `${parsed.prefix}${formatted}${parsed.suffix}`
}

function stopAnimation() {
  window.cancelAnimationFrame(animationFrame)
  window.clearTimeout(delayTimer)
}

function animate(nextValue) {
  stopAnimation()
  const parsed = parseValue(nextValue)
  const reduceMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
  if (!parsed || reduceMotion || props.duration <= 0) {
    displayValue.value = String(nextValue ?? 0)
    return
  }

  displayValue.value = formatValue(parsed, 0)
  delayTimer = window.setTimeout(() => {
    const startedAt = performance.now()
    const step = (now) => {
      const progress = Math.min((now - startedAt) / props.duration, 1)
      const eased = 1 - Math.pow(1 - progress, 3)
      displayValue.value = formatValue(parsed, parsed.number * eased)
      if (progress < 1) animationFrame = window.requestAnimationFrame(step)
    }
    animationFrame = window.requestAnimationFrame(step)
  }, props.delay)
}

watch(() => props.value, animate, { immediate: true })
onBeforeUnmount(stopAnimation)
</script>
