import React, { useState } from 'react';
import { authService } from '../services/authService';
import './LoginPage.css'; // Assuming your CSS file is named LoginPage.css
import { useNavigate } from 'react-router-dom'; // For navigation

const LoginPage: React.FC = () => {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const navigate=useNavigate();
  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    try {
      await authService.login(username, password);
      console.log('Login successful (in component)');
      navigate('/dashboard')
      // Handle successful login (e.g., redirect to protected content)
    } catch (error) {
      console.error('Login error (in component):', error);
      // Handle login errors (e.g., display error message)
    }
  };

  return (
    <div className="login-page">
      <h1>Login</h1>
      <form onSubmit={handleSubmit}>
        <div>
          <label htmlFor="username">Username:</label>
          <input type="text" id="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </div>
        <div>
          <label htmlFor="password">Password:</label>
          <input type="password" id="password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </div>
        <button type="submit">Login</button>
      </form>
    </div>
  );
};

export default LoginPage;
