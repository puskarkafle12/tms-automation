import React from 'react';
import { Routes, Route, Navigate } from 'react-router-dom';
import LoginPage from '../pages/LoginPage';
import HomePage from '../pages/HomePage';
import DashboardRoutes from './control_pannel/ControlPannelRoutes';
import NotFoundPage from '../pages/ErrorPage';
import { DASHBOARD_PATHS } from './control_pannel/dashboardPaths';
import AuthGuard from '../components/AuthGuard';

const AppRoutes = () => {
  return (
      <Routes>
        <Route path="/home" element={<HomePage />} />
        <Route path="/dashboard" element={<Navigate to={DASHBOARD_PATHS.orderLogs} replace />} />
        <Route path="/Dashboard" element={<Navigate to={DASHBOARD_PATHS.orderLogs} replace />} />
        <Route path="/dashboard/*" element={<AuthGuard><DashboardRoutes /></AuthGuard>} />
        <Route path="/Dashboard/*" element={<AuthGuard><DashboardRoutes /></AuthGuard>} />
        <Route path="/" element={<LoginPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
  );
};

export default AppRoutes;
