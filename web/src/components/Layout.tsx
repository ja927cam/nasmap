import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import { useAuth } from '../api/auth';
import Icon, { type IconName } from './Icon';

const navItems: { to: string; label: string; end?: boolean; icon: IconName }[] = [
  { to: '/', label: 'Dashboard', end: true, icon: 'dashboard' },
  { to: '/map', label: 'Map', icon: 'map' },
  { to: '/live', label: 'Live', icon: 'weather' },
  { to: '/overlays', label: 'Overlays', icon: 'layers' },
  { to: '/help', label: 'Help', icon: 'help' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
];

export default function Layout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  return (
    <div className="app-shell">
      <aside className="sidebar">
        <NavLink to="/" className="brand">
          <span className="brand-mark">
            <Icon name="layers" size={15} strokeWidth={2} />
          </span>
          <span>Strata</span>
        </NavLink>
        <nav>
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              <span className="nav-icon">
                <Icon name={item.icon} size={17} />
              </span>
              {item.label}
            </NavLink>
          ))}
          {user?.role === 'admin' && (
            <NavLink
              to="/admin"
              className={({ isActive }) => (isActive ? 'nav-item active' : 'nav-item')}
            >
              <span className="nav-icon">
                <Icon name="admin" size={17} />
              </span>
              Administration
            </NavLink>
          )}
        </nav>
        <div className="sidebar-footer">
          <div className="user-chip">
            <div className="avatar">{user?.display_name?.slice(0, 1).toUpperCase() || 'U'}</div>
            <div>
              <strong>{user?.display_name}</strong>
              <small>{user?.email}</small>
            </div>
          </div>
          <div className="sidebar-user-meta">
            <span>{user?.role}</span>
            <button
              className="sidebar-link"
              onClick={async () => {
                await logout();
                navigate('/login');
              }}
            >
              <Icon name="logout" size={14} />
              Sign out
            </button>
          </div>
        </div>
      </aside>
      <main className="main-area">
        <Outlet />
      </main>
    </div>
  );
}
