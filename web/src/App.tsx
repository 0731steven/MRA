import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { App as AntdApp } from "antd";
import LoginPage from "./pages/LoginPage";
import Sessions from "./pages/Sessions";
import ReportView from "./pages/ReportView";
import DocumentReview from "./pages/DocumentReview";
import AskPage from "./pages/AskPage";
import GuidePage from "./pages/GuidePage";
import IngestPage from "./pages/IngestPage";
import UsersPage from "./pages/UsersPage";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./components/AppLayout";

export default function App() {
  return (
    <BrowserRouter>
      <AntdApp>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/sessions"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <Sessions />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/ask/:questionId?"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <AskPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/reports/:id"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <ReportView />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/review"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <DocumentReview />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/guide"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <GuidePage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/ingest"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <IngestPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route
              path="/users"
              element={
                <ProtectedRoute>
                  <AppLayout>
                    <UsersPage />
                  </AppLayout>
                </ProtectedRoute>
              }
            />
            <Route path="*" element={<Navigate to="/sessions" replace />} />
          </Routes>
        </AuthProvider>
      </AntdApp>
    </BrowserRouter>
  );
}
