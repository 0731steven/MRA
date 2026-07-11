import type { ReactNode } from "react";
import { BookOutlined, HomeOutlined, LogoutOutlined, MessageOutlined, ReadOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const items = [
  { path: "/dashboard", label: "工作台", icon: <HomeOutlined /> },
  { path: "/tutor", label: "智能答疑", icon: <MessageOutlined /> },
  { path: "/questions", label: "题库", icon: <BookOutlined /> },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const teacher = user?.role === "teacher";
  const nav = teacher ? [...items, { path: "/teaching", label: "教学设计", icon: <ReadOutlined /> }] : items;

  return (
    <div className="min-h-screen bg-[#f6f8f7] text-slate-800">
      <header className="sticky top-0 z-20 h-16 border-b border-slate-200/80 bg-white/90 backdrop-blur-xl">
        <div className="mx-auto flex h-full max-w-[1440px] items-center px-5 lg:px-8">
          <button onClick={() => navigate("/dashboard")} className="mr-8 flex items-center gap-3">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-teal-700 to-emerald-500 text-lg font-black text-white shadow-md shadow-teal-700/20">π</span>
            <span className="hidden text-left sm:block">
              <span className="block text-[15px] font-extrabold tracking-tight text-slate-900">概率学伴</span>
              <span className="block text-[10px] font-medium tracking-wider text-slate-400">PROBABILITY TUTOR</span>
            </span>
          </button>
          <nav className="flex flex-1 items-center gap-1 overflow-x-auto">
            {nav.map(item => {
              const active = location.pathname.startsWith(item.path);
              return (
                <button key={item.path} onClick={() => navigate(item.path)} className={`flex items-center gap-2 rounded-xl px-3.5 py-2 text-sm font-semibold transition ${active ? "bg-teal-50 text-teal-800" : "text-slate-500 hover:bg-slate-50 hover:text-slate-800"}`}>
                  {item.icon}{item.label}
                </button>
              );
            })}
          </nav>
          <div className="ml-4 flex items-center gap-3 border-l border-slate-200 pl-4">
            <div className="hidden text-right md:block">
              <div className="text-sm font-bold text-slate-800">{user?.name}</div>
              <div className="text-[11px] text-slate-400">{teacher ? "教师端" : "学生端"}</div>
            </div>
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-teal-100 text-sm font-bold text-teal-800">{user?.name?.[0] || "用"}</span>
            <button aria-label="退出登录" onClick={() => { logout(); navigate("/login"); }} className="rounded-lg p-2 text-slate-400 hover:bg-rose-50 hover:text-rose-500"><LogoutOutlined /></button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-[1440px] px-5 py-7 lg:px-8">{children}</main>
    </div>
  );
}
