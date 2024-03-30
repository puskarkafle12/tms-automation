import React from 'react';
import { useNavigate } from 'react-router-dom';

const Home: React.FC = () => {
  const navigate = useNavigate();

  const handleRedirectToLogic = () => {
    navigate('/login');
  };

  return (
    <div className="home-page">
      {/* Your home page content here */}
      <button onClick={handleRedirectToLogic}>Go to Logic Route</button>
    </div>
  );
};

export default Home;
