import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { App as AntdApp, ConfigProvider } from "antd";
import LoginPage from "./pages/LoginPage";
import Dashboard from "./pages/Dashboard";
import TutorPage from "./pages/TutorPage";
import QuestionBankPage from "./pages/QuestionBankPage";
import TeachingStudio from "./pages/TeachingStudio";
import ExperimentLab from "./pages/ExperimentLab";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./components/AppLayout";

const protectedPage = (node: React.ReactNode) => (
  <ProtectedRoute><AppLayout>{node}</AppLayout></ProtectedRoute>
);

export default function App() {
  return (
    <BrowserRouter>
      <ConfigProvider theme={{ token: { colorPrimary: "#0f766e", borderRadius: 12, fontFamily: "Inter, PingFang SC, sans-serif" } }}>
        <AntdApp>
          <AuthProvider>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/dashboard" element={protectedPage(<Dashboard />)} />
              <Route path="/tutor" element={protectedPage(<TutorPage />)} />
              <Route path="/questions" element={protectedPage(<QuestionBankPage />)} />
              <Route path="/experiments" element={protectedPage(<ExperimentLab />)} />
              <Route path="/teaching" element={protectedPage(<TeachingStudio />)} />
              <Route path="*" element={<Navigate to="/dashboard" replace />} />
            </Routes>
          </AuthProvider>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}
