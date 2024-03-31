// App.tsx
import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import RoutesList from './routes'; // Import routes from the routes folder
import './App.css'; // Import CSS file for styling

function App() {
  return (
    <div className="full-container">
      <BrowserRouter>
        <RoutesList /> {/* Render routes from RoutesList component */}
      </BrowserRouter>
    </div>
  );
}

export default App;
