<template>
  <span class="inline-flex items-center gap-1 pt-1">
    <span
      v-for="index in 3"
      :key="index"
      class="typing-dot inline-block h-2 w-2 rounded-full bg-caramel"
      :style="{ animationDelay: `${(index - 1) * 0.15}s` }"
    />
  </span>
</template>
