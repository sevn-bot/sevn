/**
 * sevn.bot design tokens — TypeScript source of truth.
 *
 * Mirrors style/tokens/*.css. Import as:
 *   import { tokens, colors, gradients, typography, spacing, radius, shadows, duration, easing } from '@/style/tokens/tokens';
 */

export const colors = {
  primary: {
    pale:  '#d6ecff',
    light: '#9dd0fb',
    base:  '#5fb1f7',
    dark:  '#2a7fc6',
  },
  accent: {
    pale:  '#ffd6d6',
    light: '#ff7a7a',
    base:  '#ff3b3b',
    dark:  '#b51e1e',
  },
  base: {
    '050': '#0c0a09',
    '100': '#14110f',
    '150': '#181513',
    '200': '#26211d',
    '300': '#322c27',
    '400': '#423a33',
    a80:   'rgba(12, 10, 9, 0.80)',
    a60:   'rgba(12, 10, 9, 0.60)',
    a40:   'rgba(12, 10, 9, 0.40)',
    a20:   'rgba(12, 10, 9, 0.20)',
  },
  slate: {
    '200': '#ece7e1',
    '300': '#c8c1b8',
    '400': '#948b80',
    '500': '#6b6359',
    '600': '#4a4239',
    base:  '#c8c1b8',
  },
  light: {
    '050': '#fbf9f6',
    '100': '#f4f0ea',
    '150': '#ebe5dc',
    '200': '#ddd5c9',
    '300': '#c4baa9',
  },
  white: '#ffffff',
  status: {
    success:  '#6a9c78',
    warning:  '#c89a52',
    info:     '#5fb1f7',
    critical: '#ff3b3b',
  },
  chart: {
    '1': '#5fb1f7',
    '2': '#2a7fc6',
    '3': '#9dd0fb',
    '4': '#1a5a96',
    '5': '#bcdff9',
    anomaly: '#ff3b3b',
    grid:    'rgba(236, 231, 225, 0.06)',
    axis:    'rgba(236, 231, 225, 0.45)',
  },
  syntax: {
    fg:      '#ece7e1',
    comment: '#6b6359',
    keyword: '#5fb1f7',
    string:  '#c89a52',
    number:  '#9dd0fb',
    fn:      '#d6ecff',
    builtin: '#ff7a7a',
    punct:   '#948b80',
  },
} as const;

export const gradients = {
  brand:      'linear-gradient(135deg, #5fb1f7 0%, #ff3b3b 100%)',
  brandSoft:  'linear-gradient(135deg, rgba(95,177,247,0.85) 0%, rgba(255,59,59,0.85) 100%)',
  dark:       'linear-gradient(160deg, #181513 0%, #0c0a09 100%)',
  glowPrimary: 'radial-gradient(ellipse at center, rgba(95,177,247,0.20) 0%, rgba(95,177,247,0) 65%)',
  glowAccent:  'radial-gradient(ellipse at center, rgba(255,59,59,0.18) 0%, rgba(255,59,59,0) 65%)',
} as const;

export const typography = {
  fontFamily: {
    sans: "'Inter Tight', ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif",
    mono: "'JetBrains Mono', ui-monospace, 'SF Mono', Menlo, Consolas, monospace",
  },
  weight: { '300': 300, '400': 400, '500': 500, '600': 600, '700': 700, '800': 800 },
  size: {
    xs:   '0.6875rem',
    sm:   '0.8125rem',
    base: '0.9375rem',
    md:   '1rem',
    lg:   '1.125rem',
    xl:   '1.375rem',
    '2xl': '1.75rem',
    '3xl': '2.25rem',
    '4xl': '3rem',
    '5xl': '3.75rem',
    '6xl': '4.75rem',
  },
  lineHeight: {
    xs: 1.45, sm: 1.5, base: 1.55, md: 1.65, lg: 1.55,
    xl: 1.4, '2xl': 1.25, '3xl': 1.15, '4xl': 1.05, '5xl': 1.02, '6xl': 1.0,
  },
  tracking: {
    tightest: '-0.04em',
    tighter:  '-0.025em',
    tight:    '-0.015em',
    normal:   '0em',
    wide:     '0.02em',
    wider:    '0.06em',
    widest:   '0.14em',
  },
} as const;

export const spacing = {
  px:    '1px',
  '0_5': '0.125rem',
  '1':   '0.25rem',
  '1_5': '0.375rem',
  '2':   '0.5rem',
  '3':   '0.75rem',
  '4':   '1rem',
  '5':   '1.25rem',
  '6':   '1.5rem',
  '8':   '2rem',
  '10':  '2.5rem',
  '12':  '3rem',
  '16':  '4rem',
  '20':  '5rem',
  '24':  '6rem',
  '32':  '8rem',
} as const;

export const radius = {
  none: '0',
  sm:   '4px',
  md:   '6px',
  lg:   '8px',
  xl:   '12px',
  '2xl': '16px',
  '3xl': '24px',
  full: '9999px',
} as const;

export const shadows = {
  xs: '0 1px 0 0 rgba(0, 0, 0, 0.45)',
  sm: '0 1px 2px rgba(0, 0, 0, 0.5), 0 0 0 1px rgba(0, 0, 0, 0.45)',
  md: '0 4px 8px -2px rgba(0, 0, 0, 0.5), 0 2px 4px -2px rgba(0, 0, 0, 0.4)',
  lg: '0 12px 24px -8px rgba(0, 0, 0, 0.55), 0 4px 8px -4px rgba(0, 0, 0, 0.4)',
  xl: '0 24px 48px -12px rgba(0, 0, 0, 0.65), 0 8px 16px -4px rgba(0, 0, 0, 0.45)',
  glowPrimary: '0 0 0 1px rgba(95,177,247,0.35), 0 8px 24px -4px rgba(95,177,247,0.35)',
  glowAccent:  '0 0 0 1px rgba(255,59,59,0.40), 0 8px 24px -4px rgba(255,59,59,0.30)',
  glowBrand:   '0 0 0 1px rgba(95,177,247,0.30), 0 12px 32px -8px rgba(255,59,59,0.20), 0 12px 32px -8px rgba(95,177,247,0.20)',
} as const;

export const duration = {
  instant: '80ms',
  fast:    '140ms',
  base:    '200ms',
  slow:    '320ms',
  slower:  '500ms',
} as const;

export const easing = {
  linear:  'linear',
  out:     'cubic-bezier(0.22, 1, 0.36, 1)',
  in:      'cubic-bezier(0.55, 0, 0.78, 0.06)',
  inOut:   'cubic-bezier(0.65, 0, 0.35, 1)',
  spring:  'cubic-bezier(0.22, 1.4, 0.36, 1)',
  bounce:  'cubic-bezier(0.34, 1.56, 0.64, 1)',
} as const;

export const tokens = {
  colors,
  gradients,
  typography,
  spacing,
  radius,
  shadows,
  duration,
  easing,
} as const;

export default tokens;
export type Tokens = typeof tokens;
