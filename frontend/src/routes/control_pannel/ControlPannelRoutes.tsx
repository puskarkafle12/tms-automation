import React from 'react';
import { Routes, Route } from 'react-router-dom';
import DashBoardPage from '../../pages/control_pannel/Dashboard';
import LoginPage from '../../pages/LoginPage';
import ScheduleOrder from '../../pages/control_pannel/ScheduleOrder';

const ControlPannelRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<DashBoardPage />} />
      <Route path="/tms-login" element={<LoginPage />} />
      <Route path="/chase-stock" element={<DashBoardPage />} />
      <Route path="/add-order" element={<ScheduleOrder />} />
      <Route path="/order-status-logs" element={<DashBoardPage />} />
      <Route path="/stock-grabber" element={<DashBoardPage activeComponent="StockGrabber" />} />
    </Routes>
  );
};

export default ControlPannelRoutes;