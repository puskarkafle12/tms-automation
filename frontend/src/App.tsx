// App.tsx
import React from 'react';
import { BrowserRouter } from 'react-router-dom';
import RoutesList from './routes'; // Import routes from the routes folder

function App() {
  const handleLogin = (username: string, password: string) => {
    // Implement login logic here (e.g., API call, validation)
  };

  return (
    <BrowserRouter>
      <RoutesList /> {/* Render routes from RoutesList component */}
    </BrowserRouter>
  );
}

export default App;
