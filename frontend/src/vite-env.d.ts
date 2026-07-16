/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_MODE?: 'demo'
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
