import { lazy, Suspense } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { App as AntdApp, ConfigProvider, Spin } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./components/AppLayout";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const TutorPage = lazy(() => import("./pages/TutorPage"));
const QuestionBankPage = lazy(() => import("./pages/QuestionBankPage"));
const TeachingStudio = lazy(() => import("./pages/TeachingStudio"));
const ExperimentLab = lazy(() => import("./pages/ExperimentLab"));

const protectedPage = (node: React.ReactNode) => (
  <ProtectedRoute><AppLayout>{node}</AppLayout></ProtectedRoute>
);

export default function App() {
  return (
    <BrowserRouter>
      <ConfigProvider
        locale={zhCN}
        theme={{
          token: {
            colorPrimary: "#0f766e",
            colorInfo: "#0f766e",
            colorSuccess: "#16a34a",
            colorWarning: "#d97706",
            colorBgLayout: "#f4f7f6",
            colorText: "#1e293b",
            colorTextSecondary: "#64748b",
            borderRadius: 12,
            borderRadiusLG: 18,
            controlHeight: 40,
            fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
          },
          components: {
            Button: { fontWeight: 650, primaryShadow: "0 8px 20px rgba(15, 118, 110, 0.16)" },
            Card: { headerFontSize: 16 },
            Drawer: { paddingLG: 24 },
            Menu: { itemBorderRadius: 12, itemHeight: 46, iconSize: 17 },
            Segmented: { itemSelectedBg: "#ffffff" },
          },
        }}
      >
        <AntdApp>
          <AuthProvider>
            <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-[#f4f7f6]"><Spin size="large" tip="正在进入课程空间…"><div className="h-16 w-52" /></Spin></div>}>
              <Routes>
                <Route path="/login" element={<LoginPage />} />
                <Route path="/dashboard" element={protectedPage(<Dashboard />)} />
                <Route path="/tutor" element={protectedPage(<TutorPage />)} />
                <Route path="/questions" element={protectedPage(<QuestionBankPage />)} />
                <Route path="/experiments" element={protectedPage(<ExperimentLab />)} />
                <Route path="/teaching" element={protectedPage(<TeachingStudio />)} />
                <Route path="*" element={<Navigate to="/dashboard" replace />} />
              </Routes>
            </Suspense>
          </AuthProvider>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}
