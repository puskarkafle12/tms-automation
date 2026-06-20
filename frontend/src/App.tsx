// App.tsx
import React, { useEffect } from 'react';
import { BrowserRouter } from 'react-router-dom';
import RoutesList from './routes'; // Import routes from the routes folder
import './App.css'; // Import CSS file for styling
import { fetchServerTime } from './api/time.api';
import { setServerTodayNpt } from './utils/nepalTime';

function App() {
  useEffect(() => {
    void fetchServerTime().then((payload) => {
      setServerTodayNpt(payload.today_npt);
    });
  }, []);

  return (
    <div className="full-container">
      <BrowserRouter>
        <RoutesList /> {/* Render routes from RoutesList component */}
      </BrowserRouter>
    </div>
  );
}

export default App;
