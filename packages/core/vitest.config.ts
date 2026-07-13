import { defineConfig } from 'vitest/config'

export default defineConfig({
  test: {
    setupFiles: ['./src/test/setup.ts'],
    exclude: ['node_modules', 'dist'],
  },
})
