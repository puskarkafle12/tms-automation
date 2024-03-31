import React, { useState } from 'react';
import ErrorMessage from '../../components/ErrorMessage';

const MonitorOrders: React.FC = () => {
  const apiUrl = process.env.REACT_APP_API_URL;

  const [errorMessage, setErrorMessage] = useState<string>('');

  const handleStartClick = async () => {
    try {
      const response = await fetch(apiUrl+'/check_orders/', {
        headers: {
          'accept': 'application/json'
        }
      });
      setErrorMessage('');
      if (response.ok) {
        const data = await response.json();
        setErrorMessage(data.message);
      } else {
        const data = await response.json();
        setErrorMessage(data.message);
      }
    } catch (error) {
      setErrorMessage('Error fetching data');
    }
  };

  const handleStopClick = async () => {
    try {
      const response = await fetch(apiUrl+'/stop_check_orders/', {
        headers: {
          'accept': 'application/json'
        }
      });
      setErrorMessage('')
      if (response.ok) {
        const data = await response.json();
        setErrorMessage(data.message);
      } else {
        const data = await response.json();
        setErrorMessage(data.message);
      }
    } catch (error) {
      setErrorMessage('Error stopping monitoring');
    }
  };

  return (
    <div>
      <button onClick={handleStartClick} >Start Monitoring stocks</button>
      <button onClick={handleStopClick}>Stop Monitoring stocks</button>
      {errorMessage && <ErrorMessage message={errorMessage} />} {/* Use the ErrorMessage component */}
    </div>
  );
};

export default MonitorOrders;
