import { useEffect, useState } from "react";
import { Button, Form, Input, Segmented, message } from "antd";
import { BookOutlined, CodeOutlined, LockOutlined, UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient } from "@/api/client";

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [register, setRegister] = useState(false);
  const [loading, setLoading] = useState(false);
  const [devLoginEnabled, setDevLoginEnabled] = useState(false);
  const [devLoading, setDevLoading] = useState(false);
  useEffect(() => { if (user) navigate("/dashboard", { replace: true }); }, [user, navigate]);
  useEffect(() => {
    apiClient.get<{ enabled: boolean }>("/api/auth/dev-login/status")
      .then(res => setDevLoginEnabled(Boolean(res.data.enabled)))
      .catch(() => setDevLoginEnabled(false));
  }, []);

  async function submit(values: { username: string; password: string; name?: string; role?: string }) {
    setLoading(true);
    try {
      const res = await apiClient.post<{ token: string }>(register ? "/api/auth/register" : "/api/auth/login", values);
      await login(res.data.token);
      navigate("/dashboard", { replace: true });
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "登录失败，请检查账号信息");
    } finally { setLoading(false); }
  }

  async function devLogin() {
    setDevLoading(true);
    try {
      const res = await apiClient.post<{ token: string }>("/api/auth/dev-login");
      await login(res.data.token);
      navigate("/dashboard", { replace: true });
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      message.error(detail || "开发者登录未启用");
    } finally {
      setDevLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen overflow-hidden bg-[#eef6f3]">
      <div className="absolute inset-0 opacity-60" style={{ backgroundImage: "radial-gradient(#0f766e18 1px, transparent 1px)", backgroundSize: "24px 24px" }} />
      <section className="relative hidden w-[52%] flex-col justify-between bg-gradient-to-br from-[#083c3a] via-[#0b5b56] to-[#0f766e] p-14 text-white lg:flex">
        <div className="flex items-center gap-3"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-white/15 text-2xl font-black">π</span><span className="text-lg font-bold">概率学伴</span></div>
        <div className="max-w-xl">
          <div className="mb-5 inline-flex rounded-full border border-emerald-200/20 bg-white/10 px-4 py-1.5 text-xs font-semibold tracking-wider text-emerald-100">概率论与数理统计教学助手</div>
          <h1 className="mb-6 text-5xl font-black leading-[1.16] tracking-tight">让每一道题，<br />都成为理解概念的入口</h1>
          <p className="max-w-lg text-base leading-8 text-teal-50/75">基于 1007 道专业题库，提供可追溯的题目讲解、相似题推荐与课堂教学设计。DeepSeek 驱动，回答始终回到题目与知识点本身。</p>
          <div className="mt-10 grid grid-cols-3 gap-4">
            {[['1007','精选题目'],['双角色','教师 / 学生'],['全流程','讲解与教学']].map(([n,l]) => <div key={l} className="rounded-2xl border border-white/10 bg-white/10 p-4"><div className="text-xl font-extrabold">{n}</div><div className="mt-1 text-xs text-teal-100/60">{l}</div></div>)}
          </div>
        </div>
        <div className="text-xs text-teal-100/40">Probability & Mathematical Statistics · AI Teaching Assistant</div>
      </section>
      <section className="relative flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-[430px] rounded-[28px] border border-white bg-white/90 p-9 shadow-2xl shadow-teal-900/10 backdrop-blur-xl">
          <div className="mb-8 lg:hidden"><span className="flex h-11 w-11 items-center justify-center rounded-2xl bg-teal-700 text-2xl font-black text-white">π</span></div>
          <BookOutlined className="mb-5 text-3xl text-teal-700" />
          <h2 className="text-3xl font-black tracking-tight text-slate-900">{register ? "创建学习账号" : "欢迎回来"}</h2>
          <p className="mb-8 mt-2 text-sm text-slate-500">{register ? "选择你的身份，进入专属工作台" : "登录概率论与数理统计教学助手"}</p>
          <Form layout="vertical" requiredMark={false} onFinish={submit} initialValues={{ role: "student" }}>
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}><Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" /></Form.Item>
            {register && <Form.Item name="name" label="姓名"><Input size="large" placeholder="你的姓名或昵称" /></Form.Item>}
            {register && <Form.Item name="role" label="使用身份"><Segmented block options={[{ label: "我是学生", value: "student" }, { label: "我是教师", value: "teacher" }]} /></Form.Item>}
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 4, message: "密码至少 4 位" }]}><Input.Password size="large" prefix={<LockOutlined />} placeholder="请输入密码" /></Form.Item>
            <Button htmlType="submit" type="primary" block size="large" loading={loading} className="mt-2 !h-12 !font-bold">{register ? "注册并进入" : "登录"}</Button>
          </Form>
          {!register && devLoginEnabled && (
            <>
              <div className="my-5 flex items-center gap-3 text-xs text-slate-300"><span className="h-px flex-1 bg-slate-100" />本地开发环境<span className="h-px flex-1 bg-slate-100" /></div>
              <Button
                block
                size="large"
                icon={<CodeOutlined />}
                loading={devLoading}
                disabled={loading}
                onClick={devLogin}
                className="!h-12 !border-teal-200 !bg-teal-50 !font-bold !text-teal-800 hover:!border-teal-400 hover:!bg-teal-100"
              >
                开发者一键登录
              </Button>
              <p className="mt-2 text-center text-[11px] text-slate-400">以本地教师账号进入，仅开发环境显示</p>
            </>
          )}
          <div className="mt-7 border-t border-slate-100 pt-6 text-center text-sm text-slate-400">{register ? "已有账号？" : "还没有账号？"}<button onClick={() => setRegister(v => !v)} className="ml-2 font-bold text-teal-700">{register ? "直接登录" : "立即注册"}</button></div>
        </div>
      </section>
    </div>
  );
}
