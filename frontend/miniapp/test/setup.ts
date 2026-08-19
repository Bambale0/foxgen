import '@testing-library/jest-dom/vitest'

Object.defineProperty(window, 'Telegram', {
  configurable: true,
  value: {
    WebApp: {
      initData: 'query_id=test&user=%7B%22id%22%3A1%7D&auth_date=1&hash=test',
      initDataUnsafe: {},
      ready: () => undefined,
      expand: () => undefined,
      setHeaderColor: () => undefined,
      setBackgroundColor: () => undefined,
      setBottomBarColor: () => undefined,
      HapticFeedback: { impactOccurred: () => undefined },
    },
  },
})
