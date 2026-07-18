import React, { useEffect, useState } from 'react';
import { fetchJson } from '../../utils/api';
import { AuthUser, authService } from '../../services/authService';
import './AdminUsers.css';

type UserPage = { items: AuthUser[]; features: string[] };
type UserRole = AuthUser['role'];

const labels: Record<string, string> = {
  order_logs: 'Order logs', schedule_orders: 'Schedule orders', portfolio: 'Portfolio',
  market_analysis: 'Market analysis', stock_grabber: 'Stock grabber', strategy_details: 'Strategy details',
  backtest: 'Backtest Lab', recommendations: 'Recommendations', stock_table: 'Stock table',
  edis: 'EDIS', settings: 'Settings', tms_login: 'TMS login', admin_users: 'User administration',
};

const AdminUsers: React.FC = () => {
  const actor = authService.storedUser();
  const [data, setData] = useState<UserPage>({ items: [], features: [] });
  const [selected, setSelected] = useState<AuthUser | null>(null);
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [role, setRole] = useState<UserRole>('user');
  const [message, setMessage] = useState('');

  const load = async () => {
    const response = await fetchJson<UserPage>('/api/admin/users');
    if (!response.ok) { setMessage(response.error); return; }
    setData(response.data);
    setSelected((current) => response.data.items.find((item) => item.id === current?.id) || response.data.items[0] || null);
  };
  useEffect(() => { void load(); }, []);

  const create = async (event: React.FormEvent) => {
    event.preventDefault();
    const response = await fetchJson<{ user: AuthUser }>('/api/admin/users', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ username, password, role }),
    });
    if (!response.ok) { setMessage(response.error); return; }
    setUsername(''); setPassword(''); setMessage('User created.'); void load();
  };
  const save = async () => {
    if (!selected) return;
    const response = await fetchJson<{ user: AuthUser }>(`/api/admin/users/${selected.id}`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role: selected.role, permissions: selected.configured_permissions || selected.permissions, is_active: selected.is_active, managed_by_user_id: selected.managed_by_user_id }),
    });
    if (!response.ok) { setMessage(response.error); return; }
    setSelected(response.data.user); setMessage('Access updated and existing sessions revoked.'); void load();
  };
  const toggle = (feature: string) => setSelected((current) => {
    if (!current) return current;
    const permissions = new Set(current.configured_permissions || current.permissions);
    permissions.has(feature) ? permissions.delete(feature) : permissions.add(feature);
    return { ...current, configured_permissions: Array.from(permissions) };
  });
  const reset = async () => {
    if (!selected) return;
    const next = window.prompt(`Enter a new password for ${selected.username} (minimum 8 characters)`);
    if (!next) return;
    const response = await fetchJson<{ message: string }>(`/api/admin/users/${selected.id}/reset-password`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ new_password: next }),
    });
    setMessage(response.ok ? response.data.message : response.error);
  };

  return <div className="admin-users">
    <header><div><span>Role and access control</span><h2>User administration</h2><p>Trading data stays private. This page controls account roles and available features.</p></div><b>{data.items.length} managed users</b></header>
    {message && <div className="admin-message">{message}</div>}
    <div className="admin-grid">
      <aside>
        <form onSubmit={create}><h3>Create user</h3>
          <input placeholder="Username" value={username} onChange={(event) => setUsername(event.target.value)} required />
          <input type="password" placeholder="Temporary password" value={password} onChange={(event) => setPassword(event.target.value)} minLength={8} required />
          <select value={role} onChange={(event) => setRole(event.target.value as UserRole)}>
            <option value="user">Normal user</option>
            {actor?.role === 'superuser' && <option value="admin">Admin</option>}
            <option value="superuser">Superuser</option>
          </select><button>Create account</button>
        </form>
        <h3>Managed accounts</h3>
        {data.items.map((user) => <button className={selected?.id === user.id ? 'selected' : ''} key={user.id} onClick={() => setSelected(user)}><span>{user.username}<small>{user.role}</small></span><i className={user.is_active ? 'active' : 'disabled'}>{user.is_active ? 'active' : 'disabled'}</i></button>)}
      </aside>
      <main>{selected ? <>
        <div className="admin-user-heading"><div><h3>{selected.username}</h3><p>Created {selected.created_at?.slice(0, 10) || '—'} · Last login {selected.last_login_at?.replace('T', ' ').slice(0, 16) || 'never'}</p></div>
          <label>Role<select value={selected.role} onChange={(event) => setSelected({ ...selected, role: event.target.value as UserRole })}>
            <option value="user">Normal user</option>
            {actor?.role === 'superuser' && <option value="admin">Admin</option>}
            <option value="superuser">Superuser</option>
          </select></label>
        </div>
        <label className="account-status"><input type="checkbox" checked={selected.is_active} onChange={(event) => setSelected({ ...selected, is_active: event.target.checked })} /> Account enabled</label>
        {selected.workspace_summary && <div className="admin-workspace-summary">
          <span><b>{selected.workspace_summary.tms_accounts}</b>TMS accounts</span>
          <span><b>{selected.workspace_summary.scheduled_orders}</b>Schedules</span>
          <span><b>{selected.workspace_summary.order_logs}</b>Order logs</span>
          <span><b>{selected.workspace_summary.backtest_runs}</b>Backtests</span>
        </div>}
        <h4>Allowed tabs and actions</h4>
        <div className="permission-grid">{data.features.filter((feature) => feature !== 'admin_users' || selected.role !== 'user').map((feature) => <label key={feature} className={feature === 'stock_grabber' ? 'sensitive' : ''}><input type="checkbox" disabled={selected.role === 'superuser'} checked={selected.role === 'superuser' ? selected.permissions.includes(feature) : (selected.configured_permissions || selected.permissions).includes(feature)} onChange={() => toggle(feature)} /><span>{labels[feature] || feature}<small>{feature === 'stock_grabber' ? 'Restricted by default' : ''}</small></span></label>)}</div>
        <footer><button onClick={() => void reset()} className="secondary">Reset password</button><button onClick={() => void save()}>Save role and access</button></footer>
      </> : <div className="admin-empty">Create or select a managed user.</div>}</main>
    </div>
  </div>;
};

export default AdminUsers;
