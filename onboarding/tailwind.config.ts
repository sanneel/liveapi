import type { Config } from 'tailwindcss'

// The locked design spec, expressed once. Nothing outside this file invents a
// colour, a type size or a radius — if a value is not here, it does not ship.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        canvas: '#F6F7F4',
        surface: '#FFFFFF',
        ink: { DEFAULT: '#16191C', soft: '#454B50' },
        muted: '#7A8078',
        line: '#E4E6E0',
        accent: { DEFAULT: '#0E7A5A', weak: '#E3F1EC' },
      },
      fontFamily: {
        display: ['"Bricolage Grotesque"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'monospace'],
      },
      fontSize: {
        // The entire scale. Four sizes, nothing else.
        headline: ['clamp(30px, 5vw, 44px)', { lineHeight: '1.05', letterSpacing: '-0.02em' }],
        body: ['18px', { lineHeight: '1.6' }],
        caption: ['14px', { lineHeight: '1.5' }],
        label: ['12px', { lineHeight: '1.4', letterSpacing: '0.08em' }],
      },
      borderRadius: {
        card: '16px',
        control: '12px',
      },
      boxShadow: {
        soft: '0 2px 4px rgba(20,30,25,.04), 0 8px 24px -8px rgba(20,30,25,.10)',
        raised: '0 2px 4px rgba(20,30,25,.06), 0 12px 32px -8px rgba(20,30,25,.16)',
      },
      maxWidth: {
        column: '620px',
      },
      animation: {
        // Forward-only. There is no reverse because there is no going back.
        'step-in': 'stepIn 320ms ease forwards',
        'step-out': 'stepOut 320ms ease forwards',
        shake: 'shake 0.4s ease',
      },
      keyframes: {
        stepIn: {
          '0%': { opacity: '0', transform: 'translateX(24px)' },
          '100%': { opacity: '1', transform: 'translateX(0)' },
        },
        stepOut: {
          '0%': { opacity: '1', transform: 'translateX(0)' },
          '100%': { opacity: '0', transform: 'translateX(-24px)' },
        },
        shake: {
          '0%, 100%': { transform: 'translateX(0)' },
          '20%, 60%': { transform: 'translateX(-4px)' },
          '40%, 80%': { transform: 'translateX(4px)' },
        },
      },
    },
  },
  plugins: [],
} satisfies Config
