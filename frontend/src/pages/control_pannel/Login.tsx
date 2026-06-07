import React, { useState } from 'react';
import './Login.css';
import axios from 'axios';
import ErrorMessage from '../../components/ErrorMessage';
import { extractApiErrorMessage } from '../../utils/apiError';

const getApiUrl = () => localStorage.getItem('apiUrl') || 'http://localhost:8000';

const Login: React.FC = () => {
  const [brokerNo, setBrokerNo] = useState('');
  const [clientId, setClientId] = useState('');
  const [password, setPassword] = useState('');
  const [message, setMessage] = useState('');
  const [errorMessage, setErrorMessage] = useState('');
  const [color, setColor] = useState('lightred');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setMessage('');
    setErrorMessage('');
    try {
      const response = await axios.post(`${getApiUrl()}/login/`, {
        username: clientId,
        password,
        broker_no: brokerNo,
        stock_symbol: '',
        request_per_sec: 5,
      });

      const payload = response.data?.message || {};
      const loginMessage = payload.message || 'TMS login successful';
      const expiryNote = payload.password_expiry ? ` Expiry: ${payload.password_expiry}.` : '';
      const fullMessage = `${loginMessage}${expiryNote}`;
      if (payload.new_password_plain) {
        setPassword(payload.new_password_plain);
      }
      setColor('lightgreen');
      setMessage(fullMessage);
      setErrorMessage(fullMessage);
    } catch (error) {
      setColor('lightred');
      setErrorMessage(extractApiErrorMessage(error));
    }
  };

  return (
    <div className="login-container">
      <h2>TMS Login</h2>
      <p>Enter your plain TMS password. The backend converts it to the encoded format before calling TMS.</p>
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
          <label htmlFor="password">Password</label>
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
      {errorMessage && <ErrorMessage message={errorMessage} color={color} />}
    </div>
  );
};

export default Login;
