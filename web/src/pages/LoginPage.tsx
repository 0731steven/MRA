import { useEffect, useState } from "react";
import { Button, Form, Input, Segmented, message } from "antd";
import { BookOutlined, CheckCircleOutlined, CodeOutlined, DatabaseOutlined, LockOutlined, ReadOutlined, UserOutlined } from "@ant-design/icons";
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
    <div className="min-h-screen bg-[#f4f7f6] text-slate-800">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex h-20 max-w-7xl items-center justify-between px-6 lg:px-10">
          <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-800 text-xl font-black text-white">π</span><div><div className="text-[15px] font-extrabold tracking-tight text-slate-900">概率统计教学助手</div><div className="mt-0.5 text-sm font-medium text-slate-500">概率论与数理统计课程平台</div></div></div>
          <div className="hidden items-center gap-2 text-sm text-slate-500 sm:flex"><BookOutlined />专属课程题库</div>
        </div>
      </header>
      <main className="mx-auto grid min-h-[calc(100vh-128px)] max-w-7xl items-center gap-8 px-6 py-8 lg:grid-cols-[1.1fr_0.8fr] lg:px-10">
        <section className="rounded-2xl bg-slate-950 p-8 text-white lg:p-12">
          <p className="mb-4 text-sm font-bold text-teal-300">为大学概率统计课程而设计</p>
          <h1 className="max-w-xl text-4xl font-black leading-[1.2] tracking-tight text-white lg:text-5xl">从题库出发，<br />把解题与教学讲清楚</h1>
          <p className="mt-6 max-w-xl text-base leading-8 text-slate-300">面向大学概率论与数理统计课程，为学生提供循序渐进的题目辅导，也为教师提供可编辑、可保存的课堂教学设计。</p>
          <div className="mt-9 max-w-xl divide-y divide-slate-700 border-y border-slate-700">
            <Feature title="专属题库" detail="1007 道题及标准解析" icon={<DatabaseOutlined />} />
            <Feature title="分步辅导" detail="提示、检查与完整讲解" icon={<CheckCircleOutlined />} />
            <Feature title="教学设计" detail="生成、编辑与历史保存" icon={<ReadOutlined />} />
          </div>
          <div className="mt-7">
            <p className="text-sm font-bold text-teal-300">完整教学闭环</p>
            <ol className="mt-3 grid grid-cols-2 gap-px overflow-hidden rounded-xl bg-slate-700 sm:grid-cols-4">
              {['理解概念', '尝试作答', '获得反馈', '实验验证'].map((item, index) => <li key={item} className="bg-slate-900 p-3"><span className="text-sm font-black text-teal-300">{index + 1}</span><span className="mt-1 block text-sm font-bold text-white">{item}</span></li>)}
            </ol>
          </div>
        </section>
        <section className="flex justify-center lg:justify-end">
          <div className="w-full max-w-[440px] rounded-2xl border border-slate-200 bg-white p-8 lg:p-10">
          <div className="mb-8"><p className="mb-2 text-sm font-bold text-teal-700">账号入口</p><h2 className="text-2xl font-black tracking-tight text-slate-900">{register ? "创建账号" : "登录教学平台"}</h2><p className="mt-2 text-sm text-slate-500">{register ? "选择使用身份，进入对应工作台" : "使用你的课程平台账号继续"}</p></div>
          <Form form={form} layout="vertical" requiredMark={false} onFinish={submit} initialValues={{ role: "student" }}>
            <Form.Item name="username" label="用户名" rules={[{ required: true, message: "请输入用户名" }]}><Input size="large" prefix={<UserOutlined />} placeholder="请输入用户名" autoComplete="username" maxLength={64} /></Form.Item>
            {register && <Form.Item name="name" label="姓名"><Input size="large" placeholder="你的姓名或昵称" maxLength={64} /></Form.Item>}
            {register && <Form.Item name="role" label="使用身份"><Segmented block options={[{ label: "我是学生", value: "student" }, { label: "我是教师", value: "teacher" }]} /></Form.Item>}
            {register && selectedRole === "teacher" && <Form.Item name="teacher_code" label="教师邀请码" rules={[{ required: true, message: "请输入教师邀请码" }]}><Input.Password size="large" prefix={<LockOutlined />} placeholder="由系统部署方提供" /></Form.Item>}
            <Form.Item name="password" label="密码" rules={[{ required: true, min: 8, message: "密码至少 8 位" }]}><Input.Password size="large" prefix={<LockOutlined />} placeholder="请输入密码" autoComplete={register ? "new-password" : "current-password"} maxLength={128} /></Form.Item>
            <Button htmlType="submit" type="primary" block size="large" loading={loading} className="mt-2 !h-12 !rounded-lg !font-bold">{register ? "注册并进入" : "登录"}</Button>
          </Form>
          {!register && devLoginEnabled && (
            <>
              <div className="my-5 flex items-center gap-3 text-sm text-slate-500"><span className="h-px flex-1 bg-slate-100" />本地开发环境<span className="h-px flex-1 bg-slate-100" /></div>
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
              <p className="mt-2 text-center text-sm text-slate-500">以本地教师账号进入，仅开发环境显示</p>
            </>
          )}
          <div className="mt-7 border-t border-slate-100 pt-6 text-center text-sm text-slate-500">{register ? "已有账号？" : "还没有账号？"}<button onClick={() => setRegister(v => !v)} className="ml-2 font-bold text-teal-700">{register ? "直接登录" : "立即注册"}</button></div>
        </div>
      </section>
      </main>
      <footer className="mx-auto flex h-12 max-w-7xl items-center border-t border-slate-200 px-6 text-sm text-slate-500 lg:px-10">概率统计教学助手 · 概率论与数理统计课程支持</footer>
    </div>
  );
}

function Feature({ title, detail, icon }: { title: string; detail: string; icon: React.ReactNode }) {
  return <div className="flex items-center gap-4 py-4"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-teal-900 text-lg text-teal-200">{icon}</span><span><h3 className="text-sm font-extrabold text-white">{title}</h3><p className="mt-0.5 text-sm text-slate-300">{detail}</p></span></div>;
}
