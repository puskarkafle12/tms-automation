import React, { useState, useEffect } from 'react';
import './Settings.css';

interface SettingsProps {
  apiUrl: string;
  setApiUrl: (url: string) => void;
}

const Settings: React.FC<SettingsProps> = ({ apiUrl, setApiUrl }) => {
  const [inputValue, setInputValue] = useState(apiUrl);
  const [successMessage, setSuccessMessage] = useState('');

  const handleInputChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    setInputValue(event.target.value);
  };

  const handleSubmit = () => {
    setApiUrl(inputValue);
    localStorage.setItem('apiUrl', inputValue);
    setSuccessMessage('Successfully updated');
    setTimeout(() => setSuccessMessage(''), 3000); // Hide the message after 3 seconds
  };

  return (
    <div className="settings-popup">
      <label>
        API URL:
        <input type="text" value={inputValue} onChange={handleInputChange} />
      </label>
      <button onClick={handleSubmit}>Submit</button>
      {successMessage && <div className="success-message">{successMessage}</div>}
    </div>
  );
};

export default Settings;
