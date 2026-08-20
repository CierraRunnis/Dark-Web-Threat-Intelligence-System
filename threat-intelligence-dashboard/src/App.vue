<template>
  <router-view v-slot="{ Component }">
    <PrototypeVueShell
      v-if="route.meta.layout === 'prototype-vue'"
      :key="String(route.name || route.path)"
      :page-id="`vue:${String(route.name || route.path)}`"
      page-class="page-vue-module"
    >
      <component :is="Component" />
    </PrototypeVueShell>
    <component :is="Component" v-else />
  </router-view>
</template>

<script setup>
import { useRoute } from 'vue-router'
import PrototypeVueShell from '@/components/layout/PrototypeVueShell.vue'

const route = useRoute()
</script>
