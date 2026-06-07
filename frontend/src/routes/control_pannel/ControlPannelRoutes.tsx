import React from 'react';
import { Navigate, Route, Routes } from 'react-router-dom';
import DashBoardPage from '../../pages/control_pannel/Dashboard';
import { DASHBOARD_PATHS } from './dashboardPaths';

const dashboardSections = [
  DASHBOARD_PATHS.orderLogs,
  DASHBOARD_PATHS.tmsLogin,
  DASHBOARD_PATHS.scheduleOrder,
  DASHBOARD_PATHS.dpHoldings,
  DASHBOARD_PATHS.stockTable,
  DASHBOARD_PATHS.stockGrabber,
];

const ControlPannelRoutes = () => {
  return (
    <Routes>
      <Route path="/" element={<Navigate to={DASHBOARD_PATHS.orderLogs} replace />} />
      {dashboardSections.map((sectionPath) => {
        const section = sectionPath.replace('/dashboard/', '');
        return <Route key={sectionPath} path={section} element={<DashBoardPage />} />;
      })}
      <Route path="order-status-logs" element={<Navigate to={DASHBOARD_PATHS.orderLogs} replace />} />
      <Route path="add-order" element={<Navigate to={DASHBOARD_PATHS.scheduleOrder} replace />} />
      <Route path="chase-stock" element={<Navigate to={DASHBOARD_PATHS.orderLogs} replace />} />
      <Route path="check-orders" element={<Navigate to={DASHBOARD_PATHS.stockGrabber} replace />} />
    </Routes>
  );
};

export default ControlPannelRoutes;
