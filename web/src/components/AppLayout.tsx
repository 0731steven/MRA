import { Layout } from "antd";
import { useState, useEffect } from "react";
import type { ReactNode } from "react";
import { useNavigate, useLocation } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import {
  MessageOutlined,
  UnorderedListOutlined,
  AuditOutlined,
  LogoutOutlined,
  BookOutlined,
  CloudUploadOutlined,
  TeamOutlined,
} from "@ant-design/icons";
import { apiClient } from "@/api/client";

const { Content } = Layout;

const NAV_ICON: Record<string, ReactNode> = {
  "/ask":    <MessageOutlined />,
  "/sessions": <UnorderedListOutlined />,
  "/review": <AuditOutlined />,
  "/ingest": <CloudUploadOutlined />,
  "/users":  <TeamOutlined />,
  "/guide":  <BookOutlined />,
};

function LogoutModal({ onConfirm, onCancel }: { onConfirm: () => void; onCancel: () => void }) {
  return (
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        display: "flex", alignItems: "center", justifyContent: "center",
        background: "rgba(15,23,42,0.35)",
        backdropFilter: "blur(4px)",
        animation: "lmFadeIn 0.18s ease",
      }}
      onClick={onCancel}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 360, borderRadius: 20,
          background: "#fff",
          boxShadow: "0 24px 60px rgba(0,0,0,0.14), 0 4px 16px rgba(0,0,0,0.08)",
          padding: "32px 28px 24px",
          animation: "lmSlideUp 0.22s cubic-bezier(0.34,1.56,0.64,1)",
          textAlign: "center",
        }}
      >
        {/* icon */}
        <div style={{
          width: 56, height: 56, borderRadius: 16,
          background: "linear-gradient(135deg, #fef3c7 0%, #fde68a 100%)",
          display: "flex", alignItems: "center", justifyContent: "center",
          margin: "0 auto 18px",
          boxShadow: "0 4px 14px rgba(245,158,11,0.25)",
        }}>
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none" aria-hidden="true">
            <path d="M15 3h4a2 2 0 012 2v14a2 2 0 01-2 2h-4" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M10 17l5-5-5-5" stroke="#d97706" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            <path d="M15 12H3" stroke="#d97706" strokeWidth="2" strokeLinecap="round"/>
          </svg>
        </div>

        {/* text */}
        <p style={{ fontSize: 17, fontWeight: 700, color: "#111827", margin: "0 0 8px", letterSpacing: "-0.01em" }}>
          退出登录
        </p>
        <p style={{ fontSize: 13.5, color: "#6b7280", margin: "0 0 28px", lineHeight: 1.6 }}>
          退出后需要重新登录才能访问系统
        </p>

        {/* buttons */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={onCancel}
            style={{
              flex: 1, height: 42, borderRadius: 11,
              border: "1.5px solid #e5e7eb",
              background: "#f9fafb",
              fontSize: 14, fontWeight: 600, color: "#374151",
              cursor: "pointer",
              transition: "all 0.15s ease",
            }}
            onMouseEnter={e => { e.currentTarget.style.background = "#f3f4f6"; e.currentTarget.style.borderColor = "#d1d5db"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "#f9fafb"; e.currentTarget.style.borderColor = "#e5e7eb"; }}
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            style={{
              flex: 1, height: 42, borderRadius: 11,
              border: "none",
              background: "linear-gradient(135deg, #ef4444 0%, #dc2626 100%)",
              fontSize: 14, fontWeight: 600, color: "#fff",
              cursor: "pointer",
              boxShadow: "0 4px 12px rgba(239,68,68,0.35)",
              transition: "all 0.15s ease",
            }}
            onMouseEnter={e => { e.currentTarget.style.boxShadow = "0 6px 18px rgba(239,68,68,0.45)"; e.currentTarget.style.transform = "translateY(-1px)"; }}
            onMouseLeave={e => { e.currentTarget.style.boxShadow = "0 4px 12px rgba(239,68,68,0.35)"; e.currentTarget.style.transform = "translateY(0)"; }}
          >
            退出登录
          </button>
        </div>
      </div>

      <style>{`
        @keyframes lmFadeIn { from { opacity: 0 } to { opacity: 1 } }
        @keyframes lmSlideUp { from { opacity: 0; transform: scale(0.94) translateY(8px) } to { opacity: 1; transform: scale(1) translateY(0) } }
      `}</style>
    </div>
  );
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const [showLogout, setShowLogout] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  useEffect(() => {
    const fetchCount = () => {
      apiClient.get<{ count: number }>("/api/pending-docs/count")
        .then(res => setPendingCount(res.data.count))
        .catch(() => {});
    };
    fetchCount();
    const timer = setInterval(fetchCount, 30_000);
    window.addEventListener("pending-docs-changed", fetchCount);
    return () => {
      clearInterval(timer);
      window.removeEventListener("pending-docs-changed", fetchCount);
    };
  }, []);

  const items = [
    { key: "/ask",      label: "新建提问" },
    { key: "/sessions", label: "我的提问" },
    { key: "/review",   label: "文档审核" },
    ...(user?.role === "admin" ? [
      { key: "/ingest", label: "批量入库" },
      { key: "/users",  label: "用户管理" },
    ] : []),
    { key: "/guide",    label: "使用指南" },
  ];

  const selected = items.find((i) => location.pathname.startsWith(i.key))?.key;

  return (
    <Layout style={{ minHeight: "100vh", background: "transparent" }}>
      <div style={{
        position: "fixed", inset: 0, zIndex: -1,
        background: "linear-gradient(160deg, #f0f4ff 0%, #f8fafc 40%, #f3f0ff 100%)",
      }}>
        {/* dot grid */}
        <div style={{
          position: "absolute", inset: 0,
          backgroundImage: "radial-gradient(circle, #94a3b820 1px, transparent 1px)",
          backgroundSize: "28px 28px",
        }} />
        {/* top-left glow blob */}
        <div style={{
          position: "absolute", top: -120, left: -80,
          width: 480, height: 480, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(99,102,241,0.10) 0%, transparent 70%)",
          filter: "blur(1px)",
          pointerEvents: "none",
        }} />
        {/* bottom-right glow blob */}
        <div style={{
          position: "absolute", bottom: -100, right: -60,
          width: 420, height: 420, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(139,92,246,0.09) 0%, transparent 70%)",
          filter: "blur(1px)",
          pointerEvents: "none",
        }} />
      </div>
      <header className="h-16 flex items-center px-6 border-b border-slate-200/70 shadow-sm"
        style={{ background: "rgba(255,255,255,0.82)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)" }}
      >
        {/* logo */}
        <button
          onClick={() => navigate("/ask")}
          className="flex items-center gap-2.5 mr-8 shrink-0"
        >
          <div className="w-8 h-8 rounded-xl flex items-center justify-center shadow-md"
            style={{
              background: "linear-gradient(135deg, #6366f1 0%, #7c3aed 100%)",
              boxShadow: "0 4px 12px rgba(99,102,241,0.35), 0 1px 3px rgba(0,0,0,0.1)",
            }}>
            <span className="text-white text-sm font-bold">M</span>
          </div>
          <span className="font-semibold text-gray-800 text-[15px] hidden sm:block">
            Market Research Assistant
          </span>
        </button>

        {/* nav links */}
        <nav className="flex items-center gap-1 flex-1">
          {items.map((item) => {
            const isActive = selected === item.key;
            const badge = item.key === "/review" && pendingCount > 0 ? pendingCount : 0;
            return (
              <button
                key={item.key}
                onClick={() => navigate(item.key)}
                className={`relative flex items-center gap-1.5 px-3.5 py-2 rounded-lg text-[13px] font-semibold transition-all ${
                  isActive
                    ? "text-indigo-600"
                    : "text-gray-500 hover:text-gray-800 hover:bg-gray-50/80"
                }`}
                style={isActive ? {
                  background: "linear-gradient(135deg, rgba(99,102,241,0.10) 0%, rgba(139,92,246,0.08) 100%)",
                  boxShadow: "inset 0 0 0 1px rgba(99,102,241,0.18)",
                } : {}}
              >
                <span className={`text-[14px] ${isActive ? "text-indigo-500" : "text-gray-400"}`}>
                  {NAV_ICON[item.key]}
                </span>
                {item.label}
                {badge > 0 && (
                  <span style={{
                    display: "inline-flex", alignItems: "center", justifyContent: "center",
                    minWidth: 16, height: 16, borderRadius: 8,
                    background: "#ef4444", color: "#fff",
                    fontSize: 10, fontWeight: 700, lineHeight: 1,
                    padding: "0 4px",
                  }}>
                    {badge > 99 ? "99+" : badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        {/* right: user + logout */}
        <div className="flex items-center gap-3 shrink-0">
          {user && (
            <div className="flex items-center gap-2.5">
              {/* avatar */}
              <div style={{
                position: "relative",
                width: 34, height: 34, flexShrink: 0,
              }}>
                {/* glow ring */}
                <div style={{
                  position: "absolute", inset: -2,
                  borderRadius: "50%",
                  background: "linear-gradient(135deg, #818cf8, #6366f1, #4f46e5)",
                  opacity: 0.25,
                  filter: "blur(3px)",
                }} />
                {/* outer ring */}
                <div style={{
                  position: "absolute", inset: -1.5,
                  borderRadius: "50%",
                  background: "linear-gradient(135deg, #a5b4fc 0%, #818cf8 50%, #6366f1 100%)",
                  padding: 1.5,
                }}>
                  <div style={{ width: "100%", height: "100%", borderRadius: "50%", background: "#fff" }} />
                </div>
                {/* avatar circle */}
                <div style={{
                  position: "relative",
                  width: 34, height: 34, borderRadius: "50%",
                  background: "linear-gradient(135deg, #6366f1 0%, #4f46e5 60%, #7c3aed 100%)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  boxShadow: "0 2px 8px rgba(99,102,241,0.4)",
                }}>
                  <span style={{
                    color: "#fff",
                    fontSize: 13,
                    fontWeight: 700,
                    letterSpacing: "0.02em",
                    textTransform: "uppercase",
                    lineHeight: 1,
                  }}>
                    {user.name?.[0] ?? "U"}
                  </span>
                </div>
              </div>
              <div className="hidden md:flex flex-col" style={{ lineHeight: 1 }}>
                <span style={{ fontSize: 13, fontWeight: 600, color: "#1e293b" }}>
                  {user.name}
                </span>
                {user.role === "admin" && (
                  <span style={{
                    fontSize: 10.5, fontWeight: 600, color: "#818cf8",
                    letterSpacing: "0.04em", marginTop: 2,
                  }}>
                    管理员
                  </span>
                )}
              </div>
            </div>
          )}
          <button onClick={() => setShowLogout(true)} className="logout-btn">
            <span className="logout-icon-wrap">
              <LogoutOutlined style={{ fontSize: 12 }} />
            </span>
            <span className="hidden md:block logout-label">退出</span>
          </button>

          <style>{`
            .logout-btn {
              display: flex; align-items: center; gap: 6px;
              padding: 5px 10px 5px 5px; border-radius: 8px;
              border: none; background: transparent; cursor: pointer;
              font-size: 13px; font-weight: 500; color: #6b7280;
              transition: all 0.18s ease;
            }
            .logout-btn:hover { color: #ef4444; background: rgba(239,68,68,0.07); }
            .logout-icon-wrap {
              width: 26px; height: 26px; border-radius: 6px;
              display: flex; align-items: center; justify-content: center;
              background: rgba(107,114,128,0.1); transition: all 0.18s ease;
            }
            .logout-btn:hover .logout-icon-wrap { background: rgba(239,68,68,0.12); color: #ef4444; }
            .logout-label { transition: color 0.18s ease; }
          `}</style>
        </div>
      </header>

      <Content style={{ position: "relative" }}>{children}</Content>

      {showLogout && (
        <LogoutModal
          onConfirm={() => { setShowLogout(false); logout(); navigate("/login", { replace: true }); }}
          onCancel={() => setShowLogout(false)}
        />
      )}
    </Layout>
  );
}
