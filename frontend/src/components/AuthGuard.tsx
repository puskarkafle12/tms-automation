import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import axios from 'axios';
import { authService } from '../services/authService';

const AuthGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const hasToken = Boolean(localStorage.getItem('accessToken'));
  const [state, setState] = useState<'checking' | 'allowed' | 'denied'>(
    hasToken ? 'checking' : 'denied',
  );

  useEffect(() => {
    if (!hasToken) return;
    let cancelled = false;
    void authService
      .me()
      .then(() => {
        if (!cancelled) setState('allowed');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const status = axios.isAxiosError(error) ? error.response?.status : undefined;
        // Only a real auth rejection should clear the saved session.
        // Network blips / 502 during restart must not force another login.
        if (status === 401 || status === 403) {
          localStorage.removeItem('accessToken');
          localStorage.removeItem('userId');
          localStorage.removeItem('authUser');
          setState('denied');
          return;
        }
        setState(authService.storedUser() || localStorage.getItem('accessToken') ? 'allowed' : 'denied');
      });
    return () => {
      cancelled = true;
    };
  }, [hasToken]);

  if (state === 'denied') return <Navigate to="/" replace />;
  if (state === 'checking') return <div className="auth-loading">Checking your secure workspace…</div>;
  return <>{children}</>;
};

export default AuthGuard;
