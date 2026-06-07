import React, { useState } from 'react';
import { authService } from '../services/authService';
import './LoginPage.css'; // Assuming your CSS file is named LoginPage.css
import { useNavigate } from 'react-router-dom'; // For navigation
import ErrorMessage from '../components/ErrorMessage';
import { extractApiErrorMessage } from '../utils/apiError';
import Settings from './Settings'; // Import the Settings component
import useHotkeys from '@reecelucas/react-use-hotkeys';

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('apiUrl') || '');
  const [error, setError] = useState<string | null>(null); // State for error message
  const [showSettings, setShowSettings] = useState(false); // State to show/hide settings
  const navigate = useNavigate();

  useHotkeys('shift+s', () => {
    setShowSettings(prev => !prev);
  });
  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      setError(null);
      await authService.login(username, password);
      console.log('Login successful (in component)');
      navigate('/dashboard');
      // Handle successful login (e.g., redirect to protected content)
    } catch (error) {
      console.error('Login error (in component):', error);
      setError(extractApiErrorMessage(error));
    }
  };


  return (
    <div className="login-page">
      <h1>Login</h1>
      {error && <ErrorMessage message={error} />} {/* Conditionally render error message */}
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">Username:</label>
          <input
            type="text"
            id="username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>
        <div>
          <label htmlFor="password">Password:</label>
          <input
            type="password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>
        <button type="submit">Login</button>
      </form>
      {showSettings && <Settings />} {/* Conditionally render the Settings component */}
    </div>
  );
};

export default LoginPage;
