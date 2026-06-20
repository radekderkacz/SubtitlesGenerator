import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { readFileSync } from 'fs'
import path from 'path'

import { formatVersion } from './src/lib/version'

const pkg = JSON.parse(
  readFileSync(new URL('./package.json', import.meta.url), 'utf-8'),
) as { version: string }

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  define: {
    // CI passes APP_BUILD_SHA so every build shows a unique id (0.2.0+<sha>);
    // local builds with no sha just show the plain release version.
    __APP_VERSION__: JSON.stringify(formatVersion(pkg.version, process.env.APP_BUILD_SHA)),
  },
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
})
