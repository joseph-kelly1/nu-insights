import { render, screen, act, fireEvent } from '@testing-library/react';
import App from './App';

// react-markdown is ESM-only, which CRA's Jest does not transform.
jest.mock('react-markdown', () => (props) => props.children);
Element.prototype.scrollIntoView = () => {}; // missing in jsdom

test.each([
  ['a 429 envelope', () => Promise.resolve({ ok: false, json: async () => ({ error: 'Rate limited, try later.', code: 'rate_limited' }) }), 'Rate limited, try later.'],
  ['a network failure', () => Promise.reject(new TypeError('Failed to fetch')), 'Failed to get AI analysis. Is the backend running?'],
])('analysis shows a useful error on %s and clears Thinking', async (_, analyze, message) => {
  jest.useFakeTimers();
  global.fetch = jest.fn((url) => (url === '/api/analyze' ? analyze() : Promise.resolve({ ok: false })));
  render(<App />);
  act(() => jest.advanceTimersByTime(2000));
  fireEvent.click(screen.getAllByText('Get Started')[0]);

  const input = screen.getByPlaceholderText('Type a course code or question...');
  fireEvent.change(input, { target: { value: 'CS 3000' } });
  fireEvent.submit(input.closest('form'));

  expect(await screen.findByText(message)).toBeInTheDocument();
  expect(screen.queryByText('Thinking')).not.toBeInTheDocument();
});
