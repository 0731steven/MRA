import { Form, Input, Button, message, Spin } from "antd";
import { useAuth } from "@/contexts/AuthContext";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useEffect, useState, useRef } from "react";
import { apiClient } from "@/api/client";
import {
  UserOutlined, LockOutlined, ArrowRightOutlined,
  ThunderboltOutlined, FileSearchOutlined, TeamOutlined,
} from "@ant-design/icons";

// ── Animated canvas background ────────────────────────────────────────────────

function MeshBackground() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf: number;
    let t = 0;
    let lastTs = 0;
    let running = true;

    // Large slow blobs — wide lissajous paths  (ca/cb 大幅提升可见度)
    const blobs = [
      { ax: 0.30, ay: 0.28, rx: 0.50, ry: 0.44, fx: 0.000038, fy: 0.000062, px: 0,   py: 1.1, r: 0.60, ca: 0.38, cb: 0.18, hue: "99,102,241"  },
      { ax: 0.68, ay: 0.55, rx: 0.46, ry: 0.48, fx: 0.000050, fy: 0.000034, px: 2.0, py: 0.4, r: 0.54, ca: 0.34, cb: 0.16, hue: "139,92,246"  },
      { ax: 0.50, ay: 0.78, rx: 0.52, ry: 0.40, fx: 0.000030, fy: 0.000044, px: 1.0, py: 2.5, r: 0.58, ca: 0.30, cb: 0.14, hue: "79,70,229"   },
      { ax: 0.20, ay: 0.70, rx: 0.38, ry: 0.46, fx: 0.000056, fy: 0.000026, px: 3.5, py: 0.8, r: 0.48, ca: 0.32, cb: 0.15, hue: "167,139,250" },
      { ax: 0.80, ay: 0.25, rx: 0.42, ry: 0.50, fx: 0.000042, fy: 0.000052, px: 0.7, py: 3.1, r: 0.52, ca: 0.28, cb: 0.13, hue: "196,181,253" },
    ];

    // Floating particles — 更多、更大、更亮
    const PARTICLE_COUNT = 55;
    type Particle = { x: number; y: number; vx: number; vy: number; size: number; alpha: number; twinkle: number };
    const particles: Particle[] = Array.from({ length: PARTICLE_COUNT }, () => ({
      x:       Math.random(),
      y:       Math.random(),
      vx:      (Math.random() - 0.5) * 0.000020,
      vy:      (Math.random() - 0.5) * 0.000016,
      size:    2.5 + Math.random() * 4.5,
      alpha:   0.50 + Math.random() * 0.38,
      twinkle: Math.random() * Math.PI * 2,
    }));

    // resize 只更新尺寸，不中断循环
    function resize() {
      if (!canvas) return;
      const dpr = devicePixelRatio || 1;
      const nw = Math.round(canvas.offsetWidth  * dpr);
      const nh = Math.round(canvas.offsetHeight * dpr);
      if (nw === canvas.width && nh === canvas.height) return;
      canvas.width  = nw;
      canvas.height = nh;
    }
    resize();
    const ro = new ResizeObserver(() => resize());
    ro.observe(canvas);

    function draw(ts: number) {
      if (!running || !canvas || !ctx) return;
      const dt = lastTs ? Math.min(ts - lastTs, 50) : 16.67;
      lastTs = ts;
      t += dt;
      const W = canvas.width, H = canvas.height;
      ctx.clearRect(0, 0, W, H);

      // ── static base fill
      ctx.fillStyle = "#f5f3ff";
      ctx.fillRect(0, 0, W, H);

      // ── blobs: 更大半径 + 更强脉冲
      for (const b of blobs) {
        const ox = (b.ax + Math.sin(t * b.fx * Math.PI * 2 + b.px) * b.rx) * W;
        const oy = (b.ay + Math.cos(t * b.fy * Math.PI * 2 + b.py) * b.ry) * H;
        const pulse = 1 + Math.sin(t * 0.000080 + b.px) * 0.14;
        const radius = b.r * Math.min(W, H) * pulse;
        const g = ctx.createRadialGradient(ox, oy, 0, ox, oy, radius);
        g.addColorStop(0,    `rgba(${b.hue},${b.ca})`);
        g.addColorStop(0.45, `rgba(${b.hue},${(b.ca + b.cb) / 2})`);
        g.addColorStop(1,    `rgba(${b.hue},0)`);
        ctx.fillStyle = g;
        ctx.beginPath();
        ctx.arc(ox, oy, radius, 0, Math.PI * 2);
        ctx.fill();
      }

      // ── 3 层波浪：2 个填充 + 1 个描边线条
      for (let wave = 0; wave < 3; wave++) {
        const phase = t * 0.000120 * Math.PI * 2 + wave * (Math.PI * 0.7);
        const yBase = (0.28 + wave * 0.25) * H;
        const amp   = (0.10 - wave * 0.015) * H;          // 振幅更大
        ctx.beginPath();
        for (let x = 0; x <= W; x += 3) {
          const frac = x / W;
          const y = yBase + Math.sin(frac * Math.PI * 3.5 + phase) * amp
                          + Math.sin(frac * Math.PI * 1.8 - phase * 0.7) * amp * 0.5;
          x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
        }
        if (wave < 2) {
          ctx.lineTo(W, H); ctx.closePath();
          ctx.fillStyle = `rgba(99,102,241,${0.08 - wave * 0.02})`;
          ctx.fill();
        } else {
          // 第3条：描边线
          ctx.strokeStyle = "rgba(99,102,241,0.18)";
          ctx.lineWidth   = 1.5;
          ctx.stroke();
        }
      }

      // ── 网格点：更大、更明显
      const gridStep  = Math.round(W / 20);
      const gridStepY = Math.round(H / 13);
      for (let gx = 0; gx <= W; gx += gridStep) {
        for (let gy = 0; gy <= H; gy += gridStepY) {
          const drift = Math.sin(gx * 0.004 + t * 0.000060) * 0.06
                      + Math.cos(gy * 0.004 + t * 0.000050) * 0.06;
          const a = 0.18 + drift;
          ctx.beginPath();
          ctx.arc(gx, gy, 2.2, 0, Math.PI * 2);
          ctx.fillStyle = `rgba(99,102,241,${Math.max(0.06, Math.min(0.32, a))})`;
          ctx.fill();
        }
      }

      // ── 粒子：更亮，加光晕
      for (const p of particles) {
        p.x += p.vx * dt; p.y += p.vy * dt;
        if (p.x < 0) p.x = 1; if (p.x > 1) p.x = 0;
        if (p.y < 0) p.y = 1; if (p.y > 1) p.y = 0;
        p.twinkle += 0.004 * dt;
        const a  = p.alpha * (0.55 + 0.45 * Math.sin(p.twinkle));
        const px = p.x * W, py = p.y * H;
        // 光晕
        const glow = ctx.createRadialGradient(px, py, 0, px, py, p.size * 3);
        glow.addColorStop(0,   `rgba(99,102,241,${a * 0.35})`);
        glow.addColorStop(1,   "rgba(99,102,241,0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(px, py, p.size * 3, 0, Math.PI * 2);
        ctx.fill();
        // 核心点
        ctx.beginPath();
        ctx.arc(px, py, p.size, 0, Math.PI * 2);
        ctx.fillStyle = `rgba(99,102,241,${a})`;
        ctx.fill();
      }

      raf = requestAnimationFrame(draw);
    }
    raf = requestAnimationFrame(draw);

    // 切回标签页时重置 lastTs，防止跳帧
    function onVisible() {
      if (document.visibilityState === "visible") {
        lastTs = 0;
        if (running) raf = requestAnimationFrame(draw);
      }
    }
    document.addEventListener("visibilitychange", onVisible);

    return () => {
      running = false;
      cancelAnimationFrame(raf);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      style={{ position: "absolute", inset: 0, width: "100%", height: "100%", display: "block" }}
    />
  );
}

// ── Feature pill ──────────────────────────────────────────────────────────────

const FEATURES = [
  { icon: <FileSearchOutlined />, label: "公司知识库 + Market Engine + Web" },
  { icon: <ThunderboltOutlined />, label: "LLM 驱动，自动生成结构化报告" },
  { icon: <TeamOutlined />,        label: "团队共享，知识越用越丰富" },
];

// ── Main ──────────────────────────────────────────────────────────────────────

export default function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [isRegister, setIsRegister] = useState(false);
  const [loading, setLoading] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    const id = requestAnimationFrame(() => setMounted(true));
    return () => cancelAnimationFrame(id);
  }, []);

  const [feishuLoading, setFeishuLoading] = useState(false);

  useEffect(() => {
    if (user) { navigate("/sessions", { replace: true }); return; }
    const token = searchParams.get("token");
    if (token) {
      setFeishuLoading(true);
      login(token)
        .then(() => navigate("/sessions", { replace: true }))
        .catch(() => setFeishuLoading(false));
    }
  }, [user, searchParams, login, navigate]);

  async function handleSubmit(values: { username: string; password: string; name?: string }) {
    setLoading(true);
    try {
      const endpoint = isRegister ? "/api/auth/register" : "/api/auth/login";
      const res = await apiClient.post<{ token: string }>(endpoint, values);
      login(res.data.token);
      navigate("/sessions", { replace: true });
    } catch (err: unknown) {
      const e = err as { response?: { data?: { detail?: string } } };
      message.error(e?.response?.data?.detail || "操作失败");
    } finally {
      setLoading(false);
    }
  }

  if (feishuLoading) {
    return (
      <div style={{ minHeight: "100dvh", display: "flex", alignItems: "center", justifyContent: "center", background: "#f5f3ff", flexDirection: "column", gap: 16 }}>
        <Spin size="large" />
        <span style={{ color: "#6366f1", fontSize: 15, fontWeight: 500 }}>正在登录，请稍候…</span>
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100dvh", display: "flex", position: "relative", overflow: "hidden", fontFamily: "'Inter', 'PingFang SC', -apple-system, sans-serif" }}>
      <MeshBackground />

      {/* ── inner layout ── */}
      <div style={{ position: "relative", zIndex: 1, width: "100%", display: "flex" }}>

        {/* ── LEFT branding panel ── */}
        <div
          className="hidden lg:flex"
          style={{
            width: 480, flexShrink: 0,
            display: "flex", flexDirection: "column", justifyContent: "space-between",
            padding: "52px 52px 44px",
            opacity: mounted ? 1 : 0,
            transform: mounted ? "translateX(0)" : "translateX(-28px)",
            transition: "opacity 0.6s cubic-bezier(0.16,1,0.3,1), transform 0.6s cubic-bezier(0.16,1,0.3,1)",
          }}
        >
          {/* logo */}
          <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 13,
              background: "linear-gradient(135deg,#4f46e5,#7c3aed)",
              display: "flex", alignItems: "center", justifyContent: "center",
              boxShadow: "0 8px 24px rgba(79,70,229,0.35)",
            }}>
              <span style={{ color: "#fff", fontSize: 20, fontWeight: 800, lineHeight: 1 }}>R</span>
            </div>
            <span style={{ fontSize: 16, fontWeight: 700, color: "#1e1b4b", letterSpacing: "-0.3px" }}>
              Market Research Assistant
            </span>
          </div>

          {/* hero */}
          <div>
            <div style={{
              display: "inline-flex", alignItems: "center", gap: 6, marginBottom: 24,
              fontSize: 11, fontWeight: 700, letterSpacing: "0.09em", textTransform: "uppercase",
              color: "#7c3aed",
              background: "rgba(124,58,237,0.08)",
              border: "1px solid rgba(124,58,237,0.18)",
              padding: "5px 13px", borderRadius: 20,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#7c3aed", display: "inline-block", animation: "pulseDot 2s ease-in-out infinite" }} />
              Market Intelligence Platform
            </div>

            <h1 style={{
              fontSize: 40, fontWeight: 800, lineHeight: 1.15,
              letterSpacing: "-0.8px", color: "#1e1b4b", marginBottom: 18,
            }}>
              市场情报研究<br />
              <span style={{
                background: "linear-gradient(135deg,#4f46e5,#7c3aed,#a78bfa)",
                WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent",
              }}>从未如此高效</span>
            </h1>

            <p style={{ fontSize: 15, lineHeight: 1.75, color: "#4c4b73", marginBottom: 40, maxWidth: 340 }}>
              面向市场、产品、战略团队，整合内部知识、实时情报与公开来源，生成可追溯的深度报告。
            </p>

            <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
              {FEATURES.map((f, i) => (
                <div
                  key={f.label}
                  style={{
                    display: "flex", alignItems: "center", gap: 14,
                    padding: "12px 16px",
                    background: "rgba(255,255,255,0.6)",
                    backdropFilter: "blur(12px)",
                    border: "1px solid rgba(255,255,255,0.85)",
                    borderRadius: 12,
                    boxShadow: "0 2px 8px rgba(79,70,229,0.06)",
                    opacity: mounted ? 1 : 0,
                    transform: mounted ? "translateX(0)" : "translateX(-16px)",
                    transition: `opacity 0.5s cubic-bezier(0.16,1,0.3,1) ${0.15 + i * 0.07}s, transform 0.5s cubic-bezier(0.16,1,0.3,1) ${0.15 + i * 0.07}s`,
                  }}
                >
                  <div style={{
                    width: 34, height: 34, borderRadius: 9, flexShrink: 0,
                    background: "linear-gradient(135deg,rgba(79,70,229,0.12),rgba(124,58,237,0.10))",
                    border: "1px solid rgba(79,70,229,0.15)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 15, color: "#4f46e5",
                  }}>
                    {f.icon}
                  </div>
                  <span style={{ fontSize: 13.5, color: "#3730a3", fontWeight: 500 }}>{f.label}</span>
                </div>
              ))}
            </div>
          </div>

          <div style={{ fontSize: 12, color: "#a5b4fc" }}>
            © 2026 MRA · Southchip Market Intelligence
          </div>
        </div>

        {/* ── RIGHT login panel ── */}
        <div style={{
          flex: 1, display: "flex", alignItems: "center", justifyContent: "center",
          padding: "40px 24px",
        }}>
          {/* glow behind card */}
          <div style={{
            position: "absolute",
            width: 520, height: 520,
            borderRadius: "50%",
            background: "radial-gradient(circle, rgba(99,102,241,0.12) 0%, transparent 70%)",
            pointerEvents: "none",
            animation: "floatGlow 8s ease-in-out infinite",
          }} />

          <div style={{
            width: "100%", maxWidth: 440,
            background: "rgba(255,255,255,0.85)",
            backdropFilter: "blur(24px)",
            borderRadius: 24,
            padding: "48px 48px 44px",
            border: "1px solid rgba(255,255,255,0.95)",
            boxShadow: "0 4px 6px rgba(0,0,0,0.02), 0 24px 64px rgba(79,70,229,0.12), 0 8px 28px rgba(0,0,0,0.06)",
            position: "relative",
            opacity: mounted ? 1 : 0,
            transform: mounted ? "translateY(0) scale(1)" : "translateY(24px) scale(0.98)",
            transition: "opacity 0.55s cubic-bezier(0.16,1,0.3,1) 0.1s, transform 0.55s cubic-bezier(0.16,1,0.3,1) 0.1s",
          }}>
            {/* shimmer stripe */}
            <div style={{
              position: "absolute", top: 0, left: "10%", right: "10%", height: 2,
              background: "linear-gradient(90deg, transparent, rgba(99,102,241,0.5), rgba(167,139,250,0.6), transparent)",
              borderRadius: "0 0 4px 4px",
              animation: "shimmerLine 3s ease-in-out infinite",
            }} />

            {/* mobile logo */}
            <div className="flex lg:hidden" style={{ alignItems: "center", gap: 10, marginBottom: 28 }}>
              <div style={{
                width: 36, height: 36, borderRadius: 10,
                background: "linear-gradient(135deg,#4f46e5,#7c3aed)",
                display: "flex", alignItems: "center", justifyContent: "center",
                boxShadow: "0 4px 12px rgba(79,70,229,0.3)",
              }}>
                <span style={{ color: "#fff", fontSize: 16, fontWeight: 800 }}>R</span>
              </div>
              <span style={{ fontSize: 15, fontWeight: 700, color: "#1e1b4b" }}>Market Research Assistant</span>
            </div>

            {/* heading — crossfade on mode switch */}
            <div style={{ animation: "fadeSlideDown 0.3s cubic-bezier(0.16,1,0.3,1)" }}>
              <h2 style={{
                fontSize: 28, fontWeight: 800, color: "#1e1b4b",
                marginBottom: 6, letterSpacing: "-0.5px",
              }}>
                {isRegister ? "创建账号" : "欢迎回来"}
              </h2>
              <p style={{ fontSize: 14, color: "#6b7280", marginBottom: 36, lineHeight: 1.55 }}>
                {isRegister ? "填写信息，加入市场研究平台" : "登录以使用市场研究助手"}
              </p>
            </div>

            <Form layout="vertical" onFinish={handleSubmit} requiredMark={false} size="large" autoComplete="off">
              {/* honeypot: tricks browser autocomplete away from real fields */}
              <input type="text" style={{ display: "none" }} autoComplete="username" aria-hidden="true" readOnly />
              <input type="password" style={{ display: "none" }} autoComplete="current-password" aria-hidden="true" readOnly />
              <div style={{
                opacity: mounted ? 1 : 0,
                transform: mounted ? "translateY(0)" : "translateY(10px)",
                transition: "opacity 0.4s ease 0.25s, transform 0.4s ease 0.25s",
              }}>
                <Form.Item
                  name="username"
                  label={<span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>用户名</span>}
                  rules={[{ required: true, message: "请输入用户名" }]}
                  style={{ marginBottom: 16 }}
                >
                  <Input
                    prefix={<UserOutlined style={{ color: "#a5b4fc" }} />}
                    placeholder="请输入用户名"
                    autoComplete="off"
                    autoFocus
                    className="login-input"
                    style={{ height: 48, borderRadius: 11, fontSize: 14, border: "1.5px solid #e5e7eb" }}
                  />
                </Form.Item>
              </div>

              {isRegister && (
                <div style={{
                  animation: "expandDown 0.28s cubic-bezier(0.16,1,0.3,1)",
                  overflow: "hidden",
                }}>
                  <Form.Item
                    name="name"
                    label={<span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>显示名称</span>}
                    style={{ marginBottom: 16 }}
                  >
                    <Input
                      placeholder="选填，默认使用用户名"
                      className="login-input"
                      style={{ height: 48, borderRadius: 11, fontSize: 14, border: "1.5px solid #e5e7eb" }}
                    />
                  </Form.Item>
                </div>
              )}

              <div style={{
                opacity: mounted ? 1 : 0,
                transform: mounted ? "translateY(0)" : "translateY(10px)",
                transition: "opacity 0.4s ease 0.32s, transform 0.4s ease 0.32s",
              }}>
                <Form.Item
                  name="password"
                  label={<span style={{ fontSize: 13, fontWeight: 600, color: "#374151" }}>密码</span>}
                  rules={[{ required: true, message: "请输入密码" }]}
                  style={{ marginBottom: 32 }}
                >
                  <Input.Password
                    prefix={<LockOutlined style={{ color: "#a5b4fc" }} />}
                    placeholder="请输入密码"
                    autoComplete="off"
                    className="login-input"
                    style={{ height: 48, borderRadius: 11, fontSize: 14, border: "1.5px solid #e5e7eb" }}
                  />
                </Form.Item>
              </div>

              <div style={{
                opacity: mounted ? 1 : 0,
                transform: mounted ? "translateY(0)" : "translateY(10px)",
                transition: "opacity 0.4s ease 0.38s, transform 0.4s ease 0.38s",
              }}>
                <Form.Item style={{ marginBottom: 16 }}>
                  <Button
                    type="primary"
                    htmlType="submit"
                    block
                    loading={loading}
                    className="login-btn"
                    icon={!loading ? <ArrowRightOutlined /> : undefined}
                    style={{
                      height: 50, borderRadius: 12, fontSize: 15, fontWeight: 700,
                      background: "linear-gradient(135deg,#4f46e5 0%,#7c3aed 100%)",
                      border: "none",
                      boxShadow: "0 4px 16px rgba(79,70,229,0.4), 0 1px 3px rgba(0,0,0,0.1)",
                      display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
                      position: "relative", overflow: "hidden",
                    }}
                  >
                    {isRegister ? "注册账号" : "立即登录"}
                  </Button>
                </Form.Item>
              </div>
            </Form>

            <div style={{
              textAlign: "center", paddingTop: 20,
              borderTop: "1px solid rgba(229,231,235,0.8)",
              opacity: mounted ? 1 : 0,
              transition: "opacity 0.4s ease 0.44s",
            }}>
              <span style={{ fontSize: 13.5, color: "#9ca3af" }}>
                {isRegister ? "已有账号？" : "没有账号？"}
              </span>
              <button
                onClick={() => setIsRegister(!isRegister)}
                style={{
                  fontSize: 13.5, fontWeight: 600, color: "#4f46e5",
                  background: "none", border: "none", cursor: "pointer",
                  padding: "0 5px", marginLeft: 2,
                  transition: "color 150ms ease",
                }}
                onMouseEnter={e => (e.currentTarget.style.color = "#7c3aed")}
                onMouseLeave={e => (e.currentTarget.style.color = "#4f46e5")}
              >
                {isRegister ? "去登录" : "立即注册"}
              </button>
            </div>

            {/* ── 飞书 OAuth 登录 ── */}
            <div style={{
              marginTop: 20,
              opacity: mounted ? 1 : 0,
              transition: "opacity 0.4s ease 0.50s",
            }}>
              {/* divider */}
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 14 }}>
                <div style={{ flex: 1, height: 1, background: "linear-gradient(to right, transparent, #e5e7eb)" }} />
                <span style={{ fontSize: 11.5, color: "#b0b8c8", whiteSpace: "nowrap", letterSpacing: "0.03em" }}>或通过以下方式登录</span>
                <div style={{ flex: 1, height: 1, background: "linear-gradient(to left, transparent, #e5e7eb)" }} />
              </div>

              {/* feishu button */}
              <button
                onClick={() => { window.location.href = "/api/auth/feishu/login"; }}
                className="feishu-btn"
                aria-label="使用飞书账号登录"
              >
                {/* 飞书 logo: 蓝底 + 白色飞鸟剪影 */}
                <span className="feishu-icon-wrap" aria-hidden="true">
                  <svg width="18" height="18" viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
                    {/* left wing */}
                    <path d="M8 28 C10 22, 16 18, 22 20 C18 24, 14 27, 8 28Z" fill="white" opacity="0.95"/>
                    {/* body + right wing */}
                    <path d="M20 10 C26 12, 34 10, 36 16 C32 16, 28 18, 26 22 C22 20, 18 16, 20 10Z" fill="white" opacity="0.95"/>
                    {/* tail */}
                    <path d="M22 20 C24 26, 22 32, 18 34 C18 30, 19 26, 22 20Z" fill="white" opacity="0.85"/>
                  </svg>
                </span>
                <span className="feishu-label">飞书账号登录</span>
              </button>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

        @keyframes pulseDot {
          0%, 100% { opacity: 1; transform: scale(1); }
          50%       { opacity: 0.5; transform: scale(0.7); }
        }
        @keyframes floatGlow {
          0%, 100% { transform: translate(-10%, -10%) scale(1); }
          33%       { transform: translate(8%, -5%)  scale(1.06); }
          66%       { transform: translate(-4%, 10%) scale(0.96); }
        }
        @keyframes shimmerLine {
          0%, 100% { opacity: 0.4; transform: scaleX(0.6); }
          50%       { opacity: 1;   transform: scaleX(1); }
        }
        @keyframes fadeSlideDown {
          from { opacity: 0; transform: translateY(-8px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes expandDown {
          from { opacity: 0; max-height: 0; }
          to   { opacity: 1; max-height: 120px; }
        }

        /* input focus ring */
        .login-input .ant-input:focus,
        .login-input.ant-input:focus,
        .login-input .ant-input-focused,
        .ant-input-affix-wrapper.login-input:focus-within {
          border-color: #6366f1 !important;
          box-shadow: 0 0 0 3px rgba(99,102,241,0.15) !important;
          outline: none;
        }
        .ant-input-affix-wrapper.login-input:hover {
          border-color: #818cf8 !important;
        }
        .ant-input-affix-wrapper.login-input {
          transition: border-color 0.2s ease, box-shadow 0.2s ease !important;
        }

        /* button shine effect */
        .login-btn::before {
          content: "";
          position: absolute;
          top: 0; left: -100%;
          width: 60%; height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent);
          transform: skewX(-20deg);
          transition: none;
        }
        .login-btn:hover::before {
          animation: btnShine 0.55s ease forwards;
        }
        @keyframes btnShine {
          to { left: 150%; }
        }
        .login-btn:hover {
          transform: translateY(-2px) !important;
          box-shadow: 0 8px 24px rgba(79,70,229,0.5), 0 2px 6px rgba(0,0,0,0.12) !important;
          background: linear-gradient(135deg,#4338ca 0%,#6d28d9 100%) !important;
        }
        .login-btn:active {
          transform: translateY(0) scale(0.985) !important;
          transition: transform 0.08s ease !important;
        }
        .ant-btn-primary.login-btn {
          transition: transform 0.2s cubic-bezier(0.34,1.56,0.64,1),
                      box-shadow 0.2s ease,
                      background 0.2s ease !important;
        }

        /* feishu button */
        .feishu-btn {
          width: 100%;
          height: 46px;
          border-radius: 12px;
          border: 1.5px solid rgba(0,176,240,0.25);
          background: linear-gradient(135deg, rgba(0,176,240,0.06) 0%, rgba(0,149,255,0.06) 100%);
          display: flex;
          align-items: center;
          justify-content: center;
          gap: 10px;
          cursor: pointer;
          font-size: 14px;
          font-weight: 600;
          color: #0891b2;
          transition: all 0.22s cubic-bezier(0.34,1.56,0.64,1);
          box-shadow: 0 1px 3px rgba(0,176,240,0.08), inset 0 1px 0 rgba(255,255,255,0.6);
          position: relative;
          overflow: hidden;
          font-family: inherit;
        }
        .feishu-icon-wrap {
          width: 30px;
          height: 30px;
          border-radius: 8px;
          background: linear-gradient(135deg, #00b0f0 0%, #0087dc 100%);
          display: flex;
          align-items: center;
          justify-content: center;
          box-shadow: 0 2px 6px rgba(0,176,240,0.35);
          flex-shrink: 0;
        }
        .feishu-label {
          letter-spacing: 0.01em;
        }
        .feishu-btn::before {
          content: "";
          position: absolute;
          top: 0; left: -80%;
          width: 50%; height: 100%;
          background: linear-gradient(90deg, transparent, rgba(255,255,255,0.35), transparent);
          transform: skewX(-20deg);
        }
        .feishu-btn:hover {
          border-color: rgba(0,176,240,0.55);
          background: linear-gradient(135deg, rgba(0,176,240,0.10) 0%, rgba(0,149,255,0.10) 100%);
          box-shadow: 0 4px 14px rgba(0,176,240,0.22), inset 0 1px 0 rgba(255,255,255,0.7);
          transform: translateY(-1.5px);
          color: #0369a1;
        }
        .feishu-btn:hover::before {
          animation: btnShine 0.5s ease forwards;
        }
        .feishu-btn:active {
          transform: scale(0.985) translateY(0) !important;
          transition: transform 0.08s ease !important;
        }

        /* antd form label color */
        .ant-form-item-label > label { color: #374151 !important; }

        /* reduced-motion */
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after {
            animation-duration: 0.01ms !important;
            transition-duration: 0.01ms !important;
          }
        }
      `}</style>
    </div>
  );
}
