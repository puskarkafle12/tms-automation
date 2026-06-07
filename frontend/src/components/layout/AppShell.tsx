import React from 'react';
import './AppShell.css';
import MarketStatusBar from './MarketStatusBar';
import MonitoringNavControls from './MonitoringNavControls';
import { useMonitoringSync } from '../../hooks/useMonitoringSync';

export interface NavItem {
  id: string;
  label: string;
  icon: string;
}

interface AppShellProps {
  title: string;
  subtitle?: string;
  navItems: NavItem[];
  activeId: string;
  onNavigate: (id: string) => void;
  children: React.ReactNode;
}

const AppShell: React.FC<AppShellProps> = ({
  title,
  subtitle,
  navItems,
  activeId,
  onNavigate,
  children,
}) => {
  useMonitoringSync();

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="app-brand">
          <div className="app-brand-mark">T</div>
          <div>
            <div className="app-brand-title">TMS Automation</div>
            <div className="app-brand-sub">NEPSE Trading</div>
          </div>
        </div>
        <nav className="app-nav">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`app-nav-item ${activeId === item.id ? 'active' : ''}`}
              onClick={() => onNavigate(item.id)}
            >
              <span className="app-nav-icon">{item.icon}</span>
              <span>{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div>
            <h1 className="app-page-title">{title}</h1>
            {subtitle && <p className="app-page-subtitle">{subtitle}</p>}
          </div>
          <div className="app-topbar-right">
            <MonitoringNavControls />
            <MarketStatusBar />
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
};

export default AppShell;
