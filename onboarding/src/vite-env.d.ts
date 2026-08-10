/// <reference types="vite/client" />

// Pulls in Vite's ambient types so `import.meta.env.BASE_URL` typechecks. The SPA
// is served under a sub-path (`base: '/admin/onboarding/'`), so static assets are
// resolved against BASE_URL rather than site root.
