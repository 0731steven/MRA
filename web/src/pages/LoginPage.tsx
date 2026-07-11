import { useEffect, useState } from "react";
import { Button, Form, Input, Segmented, message } from "antd";
import { CheckCircleOutlined, CodeOutlined, DatabaseOutlined, LockOutlined, ReadOutlined, UserOutlined } from "@ant-design/icons";
import { useNavigate } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { apiClient } from "@/api/client";

export default function LoginPage() {
  const [form] = Form.useForm();
  const selectedRole = Form.useWatch("role", form);
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

  async function submit(values: { username: string; password: string; name?: string; role?: string; teacher_code?: string }) {
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
    <div className="min-h-screen bg-[#f4f6f5] text-slate-800">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6 lg:px-10">
          <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-lg bg-teal-800 text-xl font-black text-white">π</span><div><div className="text-[15px] font-extrabold tracking-tight text-slate-900">概率统计教学助手</div><div className="mt-0.5 text-[10px] font-medium tracking-[0.18em] text-slate-400">PROBABILITY & STATISTICS</div></div></div>
          <div className="hidden items-center gap-2 text-xs text-slate-400 sm:flex"><span className="h-2 w-2 rounded-full bg-emerald-500" />题库服务正常</div>
        </div>
      </header>
      <main className="mx-auto grid min-h-[calc(100vh-128px)] max-w-7xl items-center gap-12 px-6 py-12 lg:grid-cols-[1.1fr_0.8fr] lg:px-10">
        <section className="max-w-2xl">
          <p className="mb-5 text-xs font-bold tracking-[0.2em] text-teal-700">概率论与数理统计课程平台</p>
          <h1 className="max-w-xl text-4xl font-black leading-[1.25] tracking-tight text-slate-900 lg:text-5xl">从题库出发，<br />把解题与教学讲清楚</h1>
          <p className="mt-6 max-w-xl text-base leading-8 text-slate-500">面向大学概率论与数理统计课程，为学生提供循序渐进的题目辅导，也为教师提供可编辑、可保存的课堂教学设计。</p>
          <div className="mt-10 grid gap-3 sm:grid-cols-3">
            <Feature number="01" title="专属题库" detail="1007 道题及标准解析" icon={<DatabaseOutlined />} />
            <Feature number="02" title="分步辅导" detail="提示、检查与完整讲解" icon={<CheckCircleOutlined />} />
            <Feature number="03" title="教学设计" detail="生成、编辑与历史保存" icon={<ReadOutlined />} />
          </div>
          <div className="mt-8 flex flex-wrap gap-x-8 gap-y-3 border-t border-slate-200 pt-6 text-xs text-slate-400"><span>覆盖随机事件、概率分布与统计推断</span><span>学生端与教师端独立工作空间</span></div>
        </section>
        <section className="flex justify-center lg:justify-end">
          <div className="w-full max-w-[440px] rounded-2xl border border-slate-200 bg-white p-8 shadow-[0_18px_50px_rgba(15,23,42,0.07)] lg:p-10">
          <div className="mb-8"><p className="mb-2 text-xs font-bold tracking-wider text-teal-700">账号入口</p><h2 className="text-2xl font-black tracking-tight text-slate-900">{register ? "创建账号" : "登录教学平台"}</h2><p className="mt-2 text-sm text-slate-500">{register ? "选择使用身份，进入对应工作台" : "使用你的课程平台账号继续"}</p></div>
          <Form form={form} layout="vertical" requiredMark={false} onFinish={submit} initialValues={{ role: "student" }}>
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}><Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" /></Form.Item>
            {register && <Form.Item name="name" label="姓名"><Input size="large" placeholder="你的姓名或昵称" /></Form.Item>}
            {register && <Form.Item name="role" label="使用身份"><Segmented block options={[{ label: "我是学生", value: "student" }, { label: "我是教师", value: "teacher" }]} /></Form.Item>}
            {register && selectedRole === "teacher" && <Form.Item name="teacher_code" label="教师邀请码" rules={[{ required: true, message: "请输入教师邀请码" }]}><Input.Password size="large" prefix={<LockOutlined />} placeholder="由系统部署方提供" /></Form.Item>}
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}><Input.Password size="large" prefix={<LockOutlined />} placeholder="请输入密码" /></Form.Item>
            <Button htmlType="submit" type="primary" block size="large" loading={loading} className="mt-2 !h-12 !rounded-lg !font-bold">{register ? "注册并进入" : "登录"}</Button>
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
                className="!h-11 !border-slate-200 !bg-slate-50 !font-bold !text-slate-600 hover:!border-teal-300 hover:!text-teal-800"
              >
                开发者一键登录
              </Button>
              <p className="mt-2 text-center text-[11px] text-slate-400">以本地教师账号进入，仅开发环境显示</p>
            </>
          )}
          <div className="mt-7 border-t border-slate-100 pt-6 text-center text-sm text-slate-400">{register ? "已有账号？" : "还没有账号？"}<button onClick={() => setRegister(v => !v)} className="ml-2 font-bold text-teal-700">{register ? "直接登录" : "立即注册"}</button></div>
        </div>
      </section>
      </main>
      <footer className="mx-auto flex h-12 max-w-7xl items-center border-t border-slate-200 px-6 text-[11px] text-slate-400 lg:px-10">概率统计教学助手 · 概率论与数理统计课程支持</footer>
    </div>
  );
}

function Feature({ number, title, detail, icon }: { number: string; title: string; detail: string; icon: React.ReactNode }) {
  return <div className="rounded-xl border border-slate-200 bg-white p-5"><div className="flex items-center justify-between"><span className="text-lg text-teal-700">{icon}</span><span className="text-[10px] font-bold tracking-wider text-slate-300">{number}</span></div><h3 className="mt-5 text-sm font-extrabold text-slate-800">{title}</h3><p className="mt-1 text-xs leading-5 text-slate-400">{detail}</p></div>;
}
