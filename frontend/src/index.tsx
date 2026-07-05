import React from 'react';
import ReactDOM from 'react-dom/client';
import './index.css';
import App from './App';
import reportWebVitals from './reportWebVitals';
import { getDefaultApiUrl, shouldResetStoredApiUrl } from './utils/api';
import './hooks/monitoringStore';

const isNumberInput = (target: EventTarget | null): target is HTMLInputElement =>
  target instanceof HTMLInputElement && target.type === 'number';

document.addEventListener('keydown', (event) => {
  if (!isNumberInput(event.target)) {
    return;
  }
  if (['e', 'E', '+', '-'].includes(event.key)) {
    event.preventDefault();
  }
});

document.addEventListener('wheel', (event) => {
  if (isNumberInput(event.target) && document.activeElement === event.target) {
    event.preventDefault();
  }
}, { passive: false });

const savedApiUrl = localStorage.getItem('apiUrl');
if (shouldResetStoredApiUrl(savedApiUrl)) {
  localStorage.setItem('apiUrl', getDefaultApiUrl());
}

const root = ReactDOM.createRoot(
  document.getElementById('root') as HTMLElement
);
root.render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);

// If you want to start measuring performance in your app, pass a function
// to log results (for example: reportWebVitals(console.log))
// or send to an analytics endpoint. Learn more: https://bit.ly/CRA-vitals
reportWebVitals();
