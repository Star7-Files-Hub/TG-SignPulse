<template>
  <Teleport to="body">
    <div v-if="isOpen" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <!-- backdrop -->
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="$emit('close')"></div>

      <!-- modal -->
      <div :class="['relative w-full bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-800/60 shadow-xl flex flex-col', maxWidthClass || 'max-w-md']">
        <!-- header -->
        <div class="flex items-center justify-between px-5 h-14 border-b border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900">
          <div class="flex items-center gap-3">
            <h3 v-if="title" class="text-sm font-medium text-gray-900 dark:text-gray-100">{{ title }}</h3>
            <slot name="header" />
            <slot name="header-extra" />
          </div>
          <button @click="$emit('close')" class="text-gray-400 hover:text-gray-900 dark:hover:text-gray-100 transition-colors">
            <X class="w-4 h-4" />
          </button>
        </div>

        <!-- body: 支持 default slot (旧组件) 和 #body slot (新组件) -->
        <div class="p-5 overflow-y-auto max-h-[70vh] custom-scrollbar">
          <slot name="body" />
          <slot />
        </div>

        <!-- footer -->
        <div class="px-5 py-4 border-t border-gray-200 dark:border-gray-800/60 bg-gray-50 dark:bg-gray-900 flex justify-end gap-3">
          <slot name="footer" />
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { X } from 'lucide-vue-next'
defineProps<{ isOpen: boolean; maxWidthClass?: string; title?: string }>()
defineEmits<{ close: [] }>()
</script>
