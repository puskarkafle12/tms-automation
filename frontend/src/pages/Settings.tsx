import React, { useState } from 'react';
import './Settings.css'; // Assuming your CSS file is named Settings.css

const Settings: React.FC = () => {
  const [apiUrl, setApiUrl] = useState(localStorage.getItem('apiUrl') || '');
  const [message, setMessage] = useState('');

  const handleApiUrlChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setApiUrl(event.target.value);
  };

  const handleSave = () => {
    localStorage.setItem('apiUrl', apiUrl);
    setMessage('API URL successfully updated');
    setTimeout(() => setMessage(''), 3000); // Clear the message after 3 seconds
  };

  return (
    <div className="settings">
      <h2>Settings</h2>
      <div>
        <label htmlFor="apiUrl">API URL:</label>
        <input type="text" id="apiUrl" value={apiUrl} onChange={handleApiUrlChange} />
      </div>
      <button onClick={handleSave}>Save</button>
      {message && <div className="success-message">{message}</div>}
    </div>
  );
};

export default Settings;
