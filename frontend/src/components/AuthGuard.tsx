import React, { useEffect, useState } from 'react';
import { Navigate } from 'react-router-dom';
import { authService } from '../services/authService';

const AuthGuard: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const hasToken = Boolean(localStorage.getItem('accessToken'));
  const [state,setState]=useState<'checking'|'allowed'|'denied'>(hasToken?'checking':'denied');
  useEffect(()=>{if(!hasToken)return;void authService.me().then(()=>setState('allowed')).catch(()=>{localStorage.removeItem('accessToken');localStorage.removeItem('authUser');setState('denied');});},[hasToken]);
  if(state==='denied')return <Navigate to="/" replace/>;
  if(state==='checking')return <div className="auth-loading">Checking your secure workspace…</div>;
  return <>{children}</>;
};
export default AuthGuard;
