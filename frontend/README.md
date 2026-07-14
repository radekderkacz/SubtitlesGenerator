# SubtitlesGen — frontend

The React + TypeScript + Vite single-page app for SubtitlesGen. In production
it's served by the `app` container; you don't need to build or run it separately
to use SubtitlesGen — see the [root README](../README.md) for install and usage.

## Local development

```bash
npm install
npm run dev      # Vite dev server with HMR
npm run build    # type-check (tsc -b) + production build
npm run test     # vitest
```

For the full stack (backend + worker + db + redis), use the root
`docker-compose.yml`.

Stack: React 19, Vite, Tailwind, TanStack Query, Zustand, vitest. Tests live
beside the components they cover (`*.test.tsx`).
