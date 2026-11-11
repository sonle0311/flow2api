const path = require('path');

module.exports = {
  content: [path.join(__dirname, '../static/**/*.{html,js}')],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        border: '#3b3c42', input: '#50515a', ring: '#ffa07b',
        background: '#191a1d', foreground: '#f3f0eb',
        primary: { DEFAULT: '#ffa07b', foreground: '#281b15' },
        secondary: { DEFAULT: '#2b2c31', foreground: '#f3f0eb' },
        muted: { DEFAULT: '#28292e', foreground: '#b0b0b8' },
        accent: { DEFAULT: '#343238', foreground: '#f3f0eb' },
        destructive: { DEFAULT: '#c84f53', foreground: '#fff8f5' },
      },
    },
  },
  plugins: [],
};
