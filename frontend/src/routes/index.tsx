import React from 'react';
import { Routes, Route } from 'react-router-dom';
import LoginPage from '../pages/LoginPage';
import HomePage from '../pages/HomePage'; // Assuming you have a HomePage component
import DashboardRoutes from './control_pannel/ControlPannelRoutes';
import NotFoundPage from '../pages/ErrorPage';

// Wrap your routes with BrowserRouter
const AppRoutes = () => {
  return (
      <Routes>

        <Route path="/home" element={<LoginPage />} />
        <Route path="/home" element={<HomePage />} /> {/* Assuming HomePage is for authenticated users */}
        <Route path="/Dashboard/*" element={<DashboardRoutes />} /> {/* Assuming HomePage is for authenticated users */}
        <Route path="/" element={<LoginPage />} />
        <Route path="*" element={<NotFoundPage />} />
        
      </Routes>
  );
};

export default AppRoutes;
