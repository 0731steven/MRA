import { useState, type ReactNode } from "react";
import { Avatar, Button, Drawer, Dropdown, Menu, Tooltip } from "antd";
import type { MenuProps } from "antd";
import { BookOutlined, ExperimentOutlined, HomeOutlined, LogoutOutlined, MenuOutlined, MessageOutlined, ReadOutlined, RightOutlined, UserOutlined } from "@ant-design/icons";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";

const items = [
  { path: "/dashboard", label: "学习工作台", shortLabel: "工作台", icon: <HomeOutlined /> },
  { path: "/tutor", label: "智能答疑", shortLabel: "答疑", icon: <MessageOutlined /> },
  { path: "/questions", label: "课程题库", shortLabel: "题库", icon: <BookOutlined /> },
  { path: "/experiments", label: "概率实验室", shortLabel: "实验", icon: <ExperimentOutlined /> },
];

export default function AppLayout({ children }: { children: ReactNode }) {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileOpen, setMobileOpen] = useState(false);
  const teacher = user?.role === "teacher";
  const nav = teacher ? [...items, { path: "/teaching", label: "教学设计", shortLabel: "教学", icon: <ReadOutlined /> }] : items;
  const current = nav.find(item => location.pathname.startsWith(item.path)) || nav[0];
  const menuItems: MenuProps["items"] = nav.map(item => ({ key: item.path, icon: item.icon, label: item.label }));
  const accountItems: MenuProps["items"] = [
    { key: "identity", type: "group", label: teacher ? "教师账号" : "学生账号", children: [{ key: "profile", icon: <UserOutlined />, label: user?.name || "个人账号", disabled: true }] },
    { type: "divider" },
    { key: "logout", icon: <LogoutOutlined />, label: "退出登录", danger: true },
  ];

  function selectMenu({ key }: { key: string }) {
    navigate(key);
    setMobileOpen(false);
  }

  const brand = (
    <button onClick={() => navigate("/dashboard")} className="brand-button">
      <span className="brand-mark">π</span>
      <span className="min-w-0 text-left">
        <span className="block truncate text-[15px] font-extrabold tracking-tight text-slate-900">概率统计教学助手</span>
        <span className="block text-[10px] font-semibold tracking-[0.16em] text-slate-400">PROBABILITY STUDIO</span>
      </span>
    </button>
  );

  return (
    <div className="app-shell">
      <aside className="app-sidebar">
        <div className="px-5 py-6">{brand}</div>
        <div className="mx-4 mb-4 rounded-2xl border border-teal-100 bg-teal-50/70 p-3.5">
          <div className="flex items-center gap-2 text-xs font-bold text-teal-800"><span className="status-dot" />题库服务已连接</div>
          <p className="mt-1.5 text-[11px] leading-5 text-teal-700/65">1007 道概率统计题目与解析</p>
        </div>
        <p className="px-6 pb-2 pt-2 text-[10px] font-bold tracking-[0.18em] text-slate-400">课程空间</p>
        <Menu mode="inline" selectedKeys={[current.path]} items={menuItems} onClick={selectMenu} className="app-menu" />
        <div className="mt-auto p-4">
          <div className="rounded-2xl bg-slate-900 p-4 text-white">
            <p className="text-xs font-bold text-teal-300">学习小提示</p>
            <p className="mt-2 text-xs leading-5 text-slate-300">先尝试自己作答，再选择提示，学习效果会更好。</p>
            <button onClick={() => navigate("/tutor")} className="mt-3 flex items-center gap-1 text-xs font-bold text-white">开始提问 <RightOutlined className="text-[9px]" /></button>
          </div>
        </div>
      </aside>

      <div className="app-workspace">
        <header className="app-header">
          <div className="flex min-w-0 items-center gap-3">
            <Button className="!flex lg:!hidden" type="text" icon={<MenuOutlined />} onClick={() => setMobileOpen(true)} aria-label="打开导航" />
            <div className="min-w-0">
              <div className="truncate text-[15px] font-extrabold text-slate-900">{current.label}</div>
              <div className="hidden text-[11px] text-slate-400 sm:block">{teacher ? "教师工作空间" : "学生学习空间"} · 概率论与数理统计</div>
            </div>
          </div>
          <Dropdown
            menu={{ items: accountItems, onClick: ({ key }) => { if (key === "logout") { logout(); navigate("/login"); } } }}
            placement="bottomRight"
            trigger={["click"]}
          >
            <button className="account-button">
              <Avatar className="!bg-teal-100 !font-bold !text-teal-800">{user?.name?.[0] || "用"}</Avatar>
              <span className="hidden text-left sm:block"><span className="block text-sm font-bold text-slate-800">{user?.name}</span><span className="block text-[11px] text-slate-400">{teacher ? "教师端" : "学生端"}</span></span>
            </button>
          </Dropdown>
        </header>
        <main className="app-content">{children}</main>
      </div>

      <nav className="mobile-tabbar" aria-label="主导航">
        {nav.map(item => <Tooltip key={item.path} title={item.label}><button onClick={() => navigate(item.path)} className={location.pathname.startsWith(item.path) ? "active" : ""}>{item.icon}<span>{item.shortLabel}</span></button></Tooltip>)}
      </nav>

      <Drawer open={mobileOpen} onClose={() => setMobileOpen(false)} placement="left" width={286} closeIcon={false} styles={{ body: { padding: 0 } }}>
        <div className="px-5 py-6">{brand}</div>
        <Menu mode="inline" selectedKeys={[current.path]} items={menuItems} onClick={selectMenu} className="app-menu" />
      </Drawer>
    </div>
  );
}
