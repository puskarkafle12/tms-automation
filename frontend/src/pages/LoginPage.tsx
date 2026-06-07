import React, { useState } from 'react';
import { authService } from '../services/authService';
import './LoginPage.css';
import { useNavigate } from 'react-router-dom';
import ErrorMessage from '../components/ErrorMessage';
import { extractApiErrorMessage } from '../utils/apiError';
import Settings from './Settings';
import useHotkeys from '@reecelucas/react-use-hotkeys';

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [showSettings, setShowSettings] = useState(false);
  const navigate = useNavigate();

  useHotkeys('shift+s', () => {
    setShowSettings((prev) => !prev);
  });

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setError(null);
      await authService.login(username, password);
      navigate('/dashboard/order-logs');
    } catch (loginError) {
      setError(extractApiErrorMessage(loginError));
    }
  };

  return (
    <div className="login-page">
      <div className="login-page-bg" />
      <div className="login-page-card panel">
        <div className="login-page-brand">
          <div className="login-page-logo">T</div>
          <div>
            <h1>TMS Automation</h1>
            <p>Sign in to access your trading dashboard</p>
          </div>
        </div>

        {error && <ErrorMessage message={error} variant="error" />}
        <form onSubmit={handleSubmit} className="login-page-form">
          <div className="form-group">
            <label htmlFor="username">Username</label>
            <input
              type="text"
              id="username"
              className="input"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="Enter username"
              autoComplete="username"
              required
            />
          </div>
          <div className="form-group">
            <label htmlFor="password">Password</label>
            <input
              type="password"
              id="password"
              className="input"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="Enter password"
              autoComplete="current-password"
              required
            />
          </div>
          <button type="submit" className="btn btn-primary login-page-submit">
            Sign In
          </button>
        </form>
        <p className="login-page-hint">Press <kbd>Shift+S</kbd> to open API settings</p>
        {showSettings && (
          <div className="login-page-settings">
            <Settings />
          </div>
        )}
      </div>
    </div>
  );
};

export default LoginPage;
