/// <reference types="vite/client" />

/**
 * Typed environment variables. Vite only exposes variables prefixed with VITE_ to
 * client code, which is the guard that stops a server secret being bundled into
 * JavaScript that ships to a browser.
 */
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
