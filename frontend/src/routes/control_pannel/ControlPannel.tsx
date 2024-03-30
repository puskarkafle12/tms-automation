import React from 'react';
import { Routes, Route } from 'react-router-dom';
import HomePage from '../../pages/control_pannel/index'; // Assuming a dashboard home page

const DashboardRoutes = () => {
  return (
    <Routes>
      {/* Redirect to HomePage on the base Dashboard route */}
      <Route path="/" element={<HomePage />} />
    </Routes>
  );
};

export default DashboardRoutes;
