import type { Config } from 'jest'

const config: Config = {
  testEnvironment: 'jsdom',
  setupFiles: ['<rootDir>/jest.setup.ts'],
  moduleNameMapper: {
    '^@/(.*)$': '<rootDir>/$1',
    '\\.(css|less|scss|sass)$': 'identity-obj-proxy',
    '\\.(jpg|jpeg|png|gif|webp|svg|mp4|webm)$': '<rootDir>/__mocks__/fileMock.ts',
    '^next-themes$': '<rootDir>/__mocks__/next-themes.ts',
    '^framer-motion$': '<rootDir>/__mocks__/framer-motion.tsx',
    '^sonner$': '<rootDir>/__mocks__/sonner.ts',
    '^lucide-react$': '<rootDir>/__mocks__/lucide-react.tsx',
  },
  transform: {
    '^.+\\.(ts|tsx)$': ['ts-jest', {
      tsconfig: 'tsconfig.json',
      jsx: 'react-jsx',
    }],
  },
  testPathIgnorePatterns: ['/node_modules/', '/out/', '/.next/'],
  transformIgnorePatterns: [
    '/node_modules/(?!(next-themes|sonner|lucide-react|framer-motion|@radix-ui|cmdk|vaul|recharts|embla-carousel-react|react-day-picker|input-otp|react-resizable-panels)/)',
  ],
}

export default config