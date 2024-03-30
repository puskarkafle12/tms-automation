import React from 'react';
import { useNavigate } from 'react-router-dom';

const Home: React.FC = () => {
  const navigate = useNavigate();

  const handleRedirectToLogic = () => {
    navigate('/login');
  };

  return (
    <div className="container">
      {/* Your home page content here */}
      <button onClick={handleRedirectToLogic}>logout</button>
    </div>
  );
};

export default Home;
