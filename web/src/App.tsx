import { Navigate, Route, Routes } from 'react-router-dom';
import Layout from './components/Layout';
import { useAuth } from './api/auth';
import LoginPage from './pages/LoginPage';
import RegisterPage from './pages/RegisterPage';
import DashboardPage from './pages/DashboardPage';
import MapPage from './pages/MapPage';
import LivePage from './pages/LivePage';
import OverlaysPage from './pages/OverlaysPage';
import SettingsPage from './pages/SettingsPage';
import AdminPage from './pages/AdminPage';
import HelpPage from './pages/HelpPage';
import { Spinner } from './components/ui';

function Protected({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <Spinner full />;
  if (!user) return <Navigate to="/login" replace />;
  return children;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route
        path="/"
        element={
          <Protected>
            <Layout />
          </Protected>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="map" element={<MapPage />} />
        <Route path="live" element={<LivePage />} />
        <Route path="overlays" element={<OverlaysPage />} />
        <Route path="tessera" element={<Navigate to="/overlays" replace />} />
        <Route path="help" element={<HelpPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="admin" element={<AdminPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
