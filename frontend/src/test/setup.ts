import '@testing-library/jest-dom';

class ResizeObserverMock implements ResizeObserver {
  observe(_target: Element, _options?: ResizeObserverOptions) {}
  unobserve(_target: Element) {}
  disconnect() {}
}

globalThis.ResizeObserver = ResizeObserverMock;
