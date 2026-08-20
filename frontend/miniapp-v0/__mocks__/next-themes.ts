import React from 'react'

export const ThemeProvider = ({ children }: { children: React.ReactNode }) => <>{children}</>

export function useTheme() {
  return {
    theme: 'dark',
    setTheme: () => {},
    themes: ['light', 'dark'],
    resolvedTheme: 'dark',
  }
}