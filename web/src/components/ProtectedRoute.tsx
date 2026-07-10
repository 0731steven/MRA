import { Navigate } from "react-router-dom";
import { Spin } from "antd";
import type { ReactNode } from "react";
import { useAuth } from "@/contexts/AuthContext";

/** Gates a route on authentication; admin-only routes also require role==="admin". */
export default function ProtectedRoute({
  children,
  adminOnly = false,
}: {
  children: ReactNode;
  adminOnly?: boolean;
}) {
  const { user, loading } = useAuth();

  if (loading) {
    return <Spin style={{ margin: "80px auto", display: "block" }} />;
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  if (adminOnly && user.role !== "admin") {
    return <Navigate to="/sessions" replace />;
  }
  return <>{children}</>;
}
