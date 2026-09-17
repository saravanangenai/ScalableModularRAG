import { Navigate, Route, BrowserRouter as Router, Routes } from "react-router-dom";

import { AuthProvider } from "./auth/AuthProvider";
import { RequireAuth } from "./auth/RequireAuth";
import { LoginCallback } from "./pages/LoginCallback";
import { SilentRenew } from "./pages/SilentRenew";
import { WorkspaceListPage } from "./pages/WorkspaceListPage";
import { WorkspacePage } from "./pages/WorkspacePage";

function App() {
  return (
    <Router>
      <AuthProvider>
        <Routes>
          <Route path="/callback" element={<LoginCallback />} />
          <Route path="/silent-renew" element={<SilentRenew />} />
          <Route element={<RequireAuth />}>
            <Route path="/workspaces" element={<WorkspaceListPage />} />
            <Route path="/workspaces/:workspaceId" element={<WorkspacePage />} />
            <Route path="/" element={<Navigate to="/workspaces" replace />} />
          </Route>
        </Routes>
      </AuthProvider>
    </Router>
  );
}

export default App;
