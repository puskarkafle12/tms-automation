import React, { useState } from 'react';
import './Settings.css';

const Settings: React.FC = () => {
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('apiUrl') || '');
  const [message, setMessage] = useState('');

  const handleSave = () => {
    localStorage.setItem('apiUrl', apiUrl);
    setMessage('API URL saved successfully');
    setTimeout(() => setMessage(''), 3000);
  };

  return (
    <div className="settings">
      <h3 className="settings-title">API Configuration</h3>
      <div className="form-group">
        <label htmlFor="apiUrl">Backend API URL</label>
        <input
          type="text"
          id="apiUrl"
          className="input"
          value={apiUrl}
          onChange={(e) => setApiUrl(e.target.value)}
          placeholder={window.location.origin}
        />
      </div>
      <button type="button" className="btn btn-primary" onClick={handleSave}>
        Save
      </button>
      {message && <p className="settings-success">{message}</p>}
    </div>
  );
};

export default Settings;
