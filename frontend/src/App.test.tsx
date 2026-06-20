import React from 'react';
import { render, screen } from '@testing-library/react';
import App from './App';

test('renders login page at root route', () => {
  render(<App />);
  expect(screen.getByText('TMS Automation')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
});
