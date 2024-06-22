import React, { useState } from 'react';
import './Login.css';
import axios from 'axios';
import ErrorMessage from '../../components/ErrorMessage';

const Login: React.FC = () => {
  const [brokerNo, setBrokerNo] = useState('');
  const [clientId, setClientId] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage(''); // Clear any previous success message
    setErrorMessage(''); // Clear any previous error message
    try {
      const response = await axios.post('http://localhost:8000/login/', {
        username: clientId,
        password: password,
        broker_no: brokerNo,
        stock_symbol: '', // Add if necessary
        request_per_sec: 5 // Adjust as needed
      });
      if (response.status === 200) {
        setMessage(`Login successful: ${JSON.stringify(response.data.message)}`);
      } else {
        setErrorMessage('Login failed');
      }
    } catch (error) {
      if (axios.isAxiosError(error)) {
        setErrorMessage(`Error: ${error.response?.data.detail}`);
      } else {
        setErrorMessage('An unexpected error occurred');
      }
    }
  };
  
  return (
    <div className="login-container">
      <h2>Login</h2>
      <form onSubmit={handleSubmit} className="login-form">
        <div className="form-group">
          <label htmlFor="brokerNo">Broker Number</label>
          <input
            type="text"
            id="brokerNo"
            value={brokerNo}
            onChange={(e) => setBrokerNo(e.target.value)}
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="clientId">Client ID</label>
          <input
            type="text"
            id="clientId"
            value={clientId}
            onChange={(e) => setClientId(e.target.value)}
            required
          />
        </div>
        <div className="form-group">
          <label htmlFor="password">Encrypted Password</label>
          <input
            type="password"
            id="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </div>
        <button type="submit" className="login-button">Login</button>
      </form>
      {message && <div className="message">{message}</div>}
      {errorMessage && <ErrorMessage message={errorMessage} />}
    </div>
  );
};

export default Login;
