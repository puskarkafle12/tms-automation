// App.tsx
import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import RoutesList from './routes'; // Import routes from the routes folder

function App() {

  return (
    <BrowserRouter>
      <RoutesList /> {/* Render routes from RoutesList component */}
    </BrowserRouter>
  );
}

export default App;
