// Mock Telegram WebApp global
Object.defineProperty(window, 'Telegram', {
  value: {
    WebApp: {
      initData: 'mock_init_data',
      initDataUnsafe: {
        user: { id: 12345, first_name: 'Test', last_name: 'User', username: 'testuser' },
        start_param: '',
      },
      ready: () => {},
      expand: () => {},
      close: () => {},
      openLink: (url: string) => { (window as any).__openedLinks = [...((window as any).__openedLinks || []), url] },
      openTelegramLink: () => {},
      onEvent: () => {},
      offEvent: () => {},
      sendData: () => {},
      themeParams: { bg_color: '#000', text_color: '#fff' },
      colorScheme: 'dark',
      viewportHeight: 800,
      viewportStableHeight: 800,
      isExpanded: true,
      platform: 'ios',
      version: '7.0',
    },
  },
  writable: true,
})

// Mock URL.createObjectURL
URL.createObjectURL = jest.fn(() => 'blob:mock-url')
URL.revokeObjectURL = jest.fn()

// Mock scrollTo
window.scrollTo = jest.fn()

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: jest.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: jest.fn(),
    removeListener: jest.fn(),
    addEventListener: jest.fn(),
    removeEventListener: jest.fn(),
    dispatchEvent: jest.fn(),
  })),
})

// Mock IntersectionObserver
class MockIntersectionObserver {
  observe = jest.fn()
  unobserve = jest.fn()
  disconnect = jest.fn()
  root = null
  rootMargin = ''
  thresholds = []
  takeRecords = () => []
}
;(window as any).IntersectionObserver = MockIntersectionObserver

// Mock ResizeObserver
class MockResizeObserver {
  observe = jest.fn()
  unobserve = jest.fn()
  disconnect = jest.fn()
}
;(window as any).ResizeObserver = MockResizeObserver

// Suppress console errors during tests (optional)
const originalError = console.error
console.error = (...args: any[]) => {
  if (
    typeof args[0] === 'string' &&
    (args[0].includes('Warning: ReactDOM.render') ||
     args[0].includes('Not implemented: HTMLFormElement.prototype.requestSubmit'))
  ) {
    return
  }
  originalError.call(console, ...args)
}