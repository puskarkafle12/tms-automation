import React, { useState, useEffect } from 'react';
import './ErrorMessage.css';

const ErrorMessage: React.FC<{ message: string }> = ({ message }) => {
  const [isVisible, setIsVisible] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setIsVisible(false);
    }, 5000); // Hide after 5 seconds

    return () => clearTimeout(timer);
  }, []);

  return (
    <>
      {isVisible && (
        <div className="error-message show"> {/* Add the 'show' class conditionally */}
          <div>{message}</div>
          <button onClick={() => setIsVisible(false)}>Close</button>
        </div>
      )}
    </>
  );
};

export default ErrorMessage;
