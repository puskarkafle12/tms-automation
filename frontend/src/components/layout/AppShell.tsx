import React, { useEffect, useState } from 'react';
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
  canSchedule?: boolean;
  canUseGrabber?: boolean;
  children: React.ReactNode;
}

const SIDEBAR_STORAGE_KEY = 'tms-sidebar-open';

const readSidebarOpen = (): boolean => {
  if (typeof window === 'undefined') {
    return true;
  }
  const stored = window.localStorage.getItem(SIDEBAR_STORAGE_KEY);
  return stored === null ? true : stored === 'true';
};

const AppShell: React.FC<AppShellProps> = ({
  title,
  subtitle,
  navItems,
  activeId,
  onNavigate,
  canSchedule = true,
  canUseGrabber = true,
  children,
}) => {
  useMonitoringSync(canSchedule || canUseGrabber);
  const [sidebarOpen, setSidebarOpen] = useState(readSidebarOpen);

  useEffect(() => {
    window.localStorage.setItem(SIDEBAR_STORAGE_KEY, String(sidebarOpen));
  }, [sidebarOpen]);

  const toggleSidebar = () => {
    setSidebarOpen((open) => !open);
  };

  const closeSidebar = () => {
    setSidebarOpen(false);
  };

  const handleNavigate = (id: string) => {
    onNavigate(id);
    if (window.matchMedia('(max-width: 900px)').matches) {
      setSidebarOpen(false);
    }
  };

  return (
    <div className={`app-shell${sidebarOpen ? ' sidebar-open' : ' sidebar-collapsed'}`}>
      {sidebarOpen && (
        <button
          type="button"
          className="app-sidebar-backdrop"
          aria-label="Close navigation menu"
          onClick={closeSidebar}
        />
      )}
      <aside className="app-sidebar" aria-hidden={!sidebarOpen}>
        <div className="app-brand">
          <div className="app-brand-content">
            <div className="app-brand-mark">T</div>
            <div className="app-brand-text">
              <div className="app-brand-title">TMS Automation</div>
              <div className="app-brand-sub">NEPSE Trading</div>
            </div>
          </div>
          <button
            type="button"
            className="app-sidebar-close"
            aria-label="Close navigation menu"
            onClick={closeSidebar}
          >
            <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true">
              <path
                d="M6 6l12 12M18 6L6 18"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
              />
            </svg>
          </button>
        </div>
        <nav id="app-sidebar-nav" className="app-nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`app-nav-item ${activeId === item.id ? 'active' : ''}`}
              onClick={() => handleNavigate(item.id)}
            >
              <span className="app-nav-icon">{item.icon}</span>
              <span className="app-nav-label">{item.label}</span>
            </button>
          ))}
        </nav>
      </aside>
      <div className="app-main">
        <header className="app-topbar">
          <div className="app-topbar-left">
            <button
              type="button"
              className={`app-sidebar-toggle${sidebarOpen ? ' is-open' : ''}`}
              aria-label={sidebarOpen ? 'Hide navigation menu' : 'Show navigation menu'}
              aria-expanded={sidebarOpen}
              aria-controls="app-sidebar-nav"
              onClick={toggleSidebar}
            >
              <span className="app-sidebar-toggle-bar" />
              <span className="app-sidebar-toggle-bar" />
              <span className="app-sidebar-toggle-bar" />
            </button>
            <div className="app-topbar-heading">
              <h1 className="app-page-title">{title}</h1>
              {subtitle && <p className="app-page-subtitle">{subtitle}</p>}
            </div>
          </div>
          <div className="app-topbar-right">
            <MonitoringNavControls canSchedule={canSchedule} canUseGrabber={canUseGrabber} />
            <MarketStatusBar />
          </div>
        </header>
        <main className="app-content">{children}</main>
      </div>
    </div>
  );
};

export default AppShell;
