/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        plane: 'var(--plane)',
        surface: 'var(--surface)',
        'surface-2': 'var(--surface-2)',
        't1': 'var(--text-1)',
        't2': 'var(--text-2)',
        't3': 'var(--text-3)',
        grid: 'var(--grid)',
        axis: 'var(--axis)',
        edge: 'var(--border)',
        valence: 'var(--valence)',
        energy: 'var(--energy)',
        satiety: 'var(--satiety)',
        stress: 'var(--stress)',
        good: 'var(--good)',
        warning: 'var(--warning)',
        serious: 'var(--serious)',
        critical: 'var(--critical)',
        accent: 'var(--accent)',
        user: 'var(--user)',
        assistant: 'var(--assistant)',
        series: 'var(--series)',
        persona: 'var(--persona)',
      },
      boxShadow: {
        card: 'var(--shadow)',
        lg2: 'var(--shadow-lg)',
      },
      borderColor: {
        DEFAULT: 'var(--border)',
      },
    },
  },
  plugins: [],
}
