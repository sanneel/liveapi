/**
 * Build the admin CSS bundle that replaces the runtime Tailwind Play CDN.
 *
 *   npm run build:css       (one-off)
 *   npm run watch:css       (rebuild on template changes)
 *
 * Output: app/static/admin.tw.css  (committed; served as a plain stylesheet).
 * This config mirrors the inline `tailwind.config` that used to live in
 * base.html, so the generated classes are identical to what the CDN produced.
 */
module.exports = {
  content: [
    './app/templates/**/*.html',
    './app/static/**/*.js',
  ],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#06080F', 900: '#0A0D17', 850: '#0F131F', 800: '#141826', 700: '#1A1F2E', 600: '#262C3D', 500: '#3A4258' },
        brand: { 400: '#D7F340', 500: '#C2E325', 600: '#A6C311' },
        muted: { 300: '#94A0B5', 400: '#6B7891', 500: '#4A556B', 600: '#363F52' },
      },
      fontFamily: {
        sans: ['"Inter"', 'ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      fontSize: {
        'label': ['11px', { lineHeight: '14px', letterSpacing: '0.06em' }],
        'meta':  ['12px', { lineHeight: '16px' }],
        'body':  ['13px', { lineHeight: '18px' }],
        'h-sm':  ['14px', { lineHeight: '20px', fontWeight: '600' }],
        'h-md':  ['16px', { lineHeight: '22px', fontWeight: '600' }],
        'h-lg':  ['18px', { lineHeight: '24px', fontWeight: '600' }],
        'h-xl':  ['22px', { lineHeight: '28px', fontWeight: '600' }],
        'num':   ['24px', { lineHeight: '28px', fontWeight: '600' }],
      },
      borderRadius: {
        DEFAULT: '6px',
        'md':    '6px',
        'lg':    '8px',
        'xl':    '10px',
      },
      boxShadow: {
        'card': '0 1px 0 0 rgba(255,255,255,0.02) inset, 0 1px 3px 0 rgba(0,0,0,0.4)',
        'pop':  '0 4px 12px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.04)',
      },
    },
  },
  plugins: [require('@tailwindcss/forms')],
};
