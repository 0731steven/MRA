import type { ReactNode } from "react";
import { Spin } from "antd";
import { Navigate } from "react-router-dom";

import { useAuth } from "@/contexts/AuthContext";


export default function ProtectedRoute({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  if (loading) return <Spin style={{ margin: "80px auto", display: "block" }} />;
  if (!user) return <Navigate to="/login" replace />;
  return <>{children}</>;
}
