/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{js,jsx}',
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        // Clinical platform brand colors
        clinical: {
          blue: '#1E6FD9',
          'blue-light': '#EBF3FD',
          green: '#1A7F5A',
          'green-light': '#E8F5EF',
        },
        // NER highlight colors
        ner: {
          medication: '#2563EB',    // blue
          'medication-bg': '#DBEAFE',
          symptom: '#D97706',       // amber
          'symptom-bg': '#FEF3C7',
          diagnosis: '#DC2626',     // red
          'diagnosis-bg': '#FEE2E2',
        },
        // Severity colors for drug interactions
        severity: {
          low: '#16A34A',
          medium: '#D97706',
          high: '#DC2626',
          critical: '#7C3AED',
        },
        // Confidence score colors
        confidence: {
          high: '#16A34A',
          medium: '#D97706',
          low: '#DC2626',
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
      animation: {
        'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.3s ease-in-out',
        'slide-up': 'slideUp 0.3s ease-out',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0' },
          '100%': { opacity: '1' },
        },
        slideUp: {
          '0%': { transform: 'translateY(10px)', opacity: '0' },
          '100%': { transform: 'translateY(0)', opacity: '1' },
        },
      },
    },
  },
  plugins: [],
}