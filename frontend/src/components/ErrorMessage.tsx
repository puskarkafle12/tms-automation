import React, { useState, useEffect } from 'react';
import './ErrorMessage.css';

const ErrorMessage: React.FC<{ message: string, color?: string }> = ({ message, color = 'lightred' }) => {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false);
    }, 5000); // Hide after 5 seconds

    return () => clearTimeout(timer);
  }, []);

  const errorMessageStyle = {
    backgroundColor: color, // Set the background color dynamically
  };

  return (
    <>
      {isVisible && (
        <div className="error-message show" style={errorMessageStyle}>
          <div>{message}</div>
          <button onClick={() => setIsVisible(false)}>Close</button>
        </div>
      )}
    </>
  );
};

export default ErrorMessage;
