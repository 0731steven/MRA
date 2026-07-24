import { lazy, Suspense, useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { App as AntdApp, ConfigProvider, Spin } from "antd";
import zhCN from "antd/locale/zh_CN";
import { AuthProvider } from "./contexts/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import AppLayout from "./components/AppLayout";
import AppErrorBoundary from "./components/AppErrorBoundary";

const LoginPage = lazy(() => import("./pages/LoginPage"));
const Dashboard = lazy(() => import("./pages/Dashboard"));
const TutorPage = lazy(() => import("./pages/TutorPage"));
const QuestionBankPage = lazy(() => import("./pages/QuestionBankPage"));
const TeachingStudio = lazy(() => import("./pages/TeachingStudio"));
const ExperimentLab = lazy(() => import("./pages/ExperimentLab"));
const LearningPathPage = lazy(() => import("./pages/LearningPathPage"));
const ClassroomRadarPage = lazy(() => import("./pages/ClassroomRadarPage"));
const MyTasksPage = lazy(() => import("./pages/MyTasksPage"));

const protectedPage = (node: React.ReactNode) => (
  <ProtectedRoute><AppLayout>{node}</AppLayout></ProtectedRoute>
);

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo({ top: 0, left: 0, behavior: "auto" });
  }, [pathname]);
  return null;
}

export default function App() {
  const routerBase = import.meta.env.BASE_URL.replace(/\/$/, "") || "/";

  return (
    <BrowserRouter basename={routerBase}>
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
            colorTextPlaceholder: "#64748b",
            colorBorder: "#cbd5e1",
            borderRadius: 12,
            borderRadiusLG: 16,
            controlHeight: 40,
            fontSizeSM: 13,
            fontFamily: "ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'PingFang SC', 'Microsoft YaHei', sans-serif",
          },
          components: {
            Button: { fontWeight: 650, primaryShadow: "0 2px 4px rgba(15, 118, 110, 0.16)" },
            Card: { headerFontSize: 16 },
            Drawer: { paddingLG: 24 },
            Menu: { itemBorderRadius: 12, itemHeight: 46, iconSize: 17 },
            Segmented: { itemSelectedBg: "#ffffff" },
          },
        }}
      >
        <AntdApp>
          <AppErrorBoundary>
            <AuthProvider>
              <ScrollToTop />
              <Suspense fallback={<div className="flex min-h-screen items-center justify-center bg-[#f4f7f6]" aria-live="polite"><Spin size="large" tip="正在进入课程空间…"><div className="h-16 w-52" /></Spin></div>}>
                <Routes>
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/dashboard" element={protectedPage(<Dashboard />)} />
                  <Route path="/tutor" element={protectedPage(<TutorPage />)} />
                  <Route path="/questions" element={protectedPage(<QuestionBankPage />)} />
                  <Route path="/experiments" element={protectedPage(<ExperimentLab />)} />
                  <Route path="/learning-path" element={protectedPage(<LearningPathPage />)} />
                  <Route path="/classrooms" element={protectedPage(<ClassroomRadarPage />)} />
                  <Route path="/tasks" element={protectedPage(<MyTasksPage />)} />
                  <Route path="/teaching" element={protectedPage(<TeachingStudio />)} />
                  <Route path="*" element={<Navigate to="/dashboard" replace />} />
                </Routes>
              </Suspense>
            </AuthProvider>
          </AppErrorBoundary>
        </AntdApp>
      </ConfigProvider>
    </BrowserRouter>
  );
}
