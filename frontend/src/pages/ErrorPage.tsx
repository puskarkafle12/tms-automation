import React from 'react';
import { Link } from 'react-router-dom';

const NotFoundPage = () => {
  return (
    <div className="not-found">
      <h1>404: Page Not Found</h1>
      <p>
        The page you requested could not be found. It may have been removed, or
        you may have typed the address incorrectly.
      </p>
      <Link to="/">Go Back Home</Link>
    </div>
  );
};

export default NotFoundPage;

// // Optional styles (add to your CSS file)
// .not-found {
//   text-align: center;
//   padding: 50px;
// }

// .not-found h1 {
//   font-size: 2em;
//   margin-bottom: 20px;
// }
