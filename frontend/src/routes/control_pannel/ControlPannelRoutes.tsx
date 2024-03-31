import React from 'react';
import { Routes, Route } from 'react-router-dom';
import DashBoardPage from '../../pages/control_pannel/Dashboard'; // Assuming a dashboard home page
import LoginPage from '../../pages/LoginPage';
import ScheduleOrder from '../../pages/control_pannel/ScheduleOrder';

const DashboardRoutes = () => {
  return (
    <Routes>
      {/* Redirect to DashBoardPage on the base Dashboard route */}
      <Route path="/" element={<DashBoardPage />} />
      <Route path="/tms-login" element={<LoginPage />} />
      <Route path="/chase-stock" element={<DashBoardPage />} />
      <Route path="/add-order" element={<ScheduleOrder />} />
      <Route path="/order-status-logs" element={<DashBoardPage />} />
    </Routes>
  );
};

export default DashboardRoutes;
