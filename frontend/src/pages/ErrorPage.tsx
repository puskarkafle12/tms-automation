import React from 'react';
import { Link } from 'react-router-dom';
import './ErrorPage.css';

const NotFoundPage = () => {
  return (
    <div className="error-page">
      <div className="error-page-card panel">
        <h1>404</h1>
        <h2>Page Not Found</h2>
        <p>The page you requested could not be found.</p>
        <Link to="/" className="btn btn-primary">Back to Login</Link>
      </div>
    </div>
  );
};

export default NotFoundPage;
