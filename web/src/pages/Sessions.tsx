import { useEffect, useState, useCallback, useMemo } from "react";
import { Modal, Popconfirm, Spin, message, Alert, Input } from "antd";
import { useNavigate, useLocation, useSearchParams } from "react-router-dom";
import {
  PlusOutlined,
  FileTextOutlined,
  DeleteOutlined,
  ClockCircleOutlined,
  CheckCircleFilled,
  ExclamationCircleFilled,
  StopOutlined,
  RightOutlined,
  ThunderboltOutlined,
  UnorderedListOutlined,
  SearchOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

interface Question {
  id: number;
  raw_text: string;
  tier: string;
  status: string;
  created_at: string;
  report_id: number | null;
  user_name?: string;
  user_id?: number;
}

interface DocItem {
  id: number;
  source: string;
  title: string;
  status: string;
  staging_exists: boolean;
  target_exists: boolean;
  staging_path: string;
  target_path: string;
}

interface DeletePreview {
  report: { path: string; exists: boolean };
  qa_files: string[];
  documents: DocItem[];
}

const TIER_CONFIG: Record<string, { label: string; icon: React.ReactNode; color: string; bg: string; border: string }> = {
  quick:  { label: "快速", icon: <ThunderboltOutlined />, color: "#d97706", bg: "#fffbeb", border: "#fde68a" },
  normal: { label: "标准", icon: <UnorderedListOutlined />, color: "#2563eb", bg: "#eff6ff", border: "#bfdbfe" },
  deep:   { label: "深度", icon: <SearchOutlined />, color: "#7c3aed", bg: "#f5f3ff", border: "#ddd6fe" },
};

const SOURCE_LABEL: Record<string, string> = { ieee: "IEEE", patent: "专利", web: "Web" };

const STATUS_CONFIG: Record<string, { label: string; dot: string; text: string; bg: string; border: string }> = {
  done:      { label: "已完成", dot: "#10b981", text: "#059669", bg: "#ecfdf5", border: "#a7f3d0" },
  running:   { label: "运行中", dot: "#3b82f6", text: "#2563eb", bg: "#eff6ff", border: "#bfdbfe" },
  failed:    { label: "失败",   dot: "#ef4444", text: "#dc2626", bg: "#fef2f2", border: "#fecaca" },
  cancelled: { label: "已取消", dot: "#9ca3af", text: "#6b7280", bg: "#f9fafb", border: "#e5e7eb" },
};

function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CONFIG[status] ?? STATUS_CONFIG.running;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      fontSize: 11, fontWeight: 600, padding: "2px 8px",
      borderRadius: 20, border: `1px solid ${cfg.border}`,
      background: cfg.bg, color: cfg.text,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: "50%", background: cfg.dot, flexShrink: 0, display: "inline-block" }} />
      {cfg.label}
    </span>
  );
}

function getDateGroup(dateStr: string): string {
  const d = new Date(dateStr);
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const yesterday = new Date(today.getTime() - 86400000);
  const itemDay = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  if (itemDay.getTime() === today.getTime()) return "今天";
  if (itemDay.getTime() === yesterday.getTime()) return "昨天";
  const diffDays = Math.floor((today.getTime() - itemDay.getTime()) / 86400000);
  if (diffDays < 7) return "本周";
  if (d.getFullYear() === now.getFullYear()) return `${d.getMonth() + 1} 月`;
  return `${d.getFullYear()} 年`;
}

const GROUP_ORDER = ["今天", "昨天", "本周"];

export default function Sessions() {
  const [questions, setQuestions] = useState<Question[]>([]);
  const [loading, setLoading] = useState(true);
  const [searchText, setSearchText] = useState("");
  const navigate = useNavigate();
  const location = useLocation();
  const { user: currentUser } = useAuth();
  const isAdmin = currentUser?.role === "admin";

  const [modalOpen, setModalOpen] = useState(false);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [targetReportId, setTargetReportId] = useState<number | null>(null);
  const [targetQuestionId, setTargetQuestionId] = useState<number | null>(null);
  const [preview, setPreview] = useState<DeletePreview | null>(null);

  useEffect(() => {
    setLoading(true);
    apiClient.get<Question[]>("/api/questions")
      .then(res => setQuestions(res.data))
      .finally(() => setLoading(false));
  }, [location.key]);

  const resolveReportId = async (q: Question): Promise<number | null> => {
    if (q.report_id) return q.report_id;
    try {
      const res = await apiClient.get<{ report_id: number | null }>(`/api/questions/${q.id}`);
      const rid = res.data.report_id;
      if (rid) setQuestions(prev => prev.map(x => x.id === q.id ? { ...x, report_id: rid } : x));
      return rid;
    } catch { return null; }
  };

  const openDeleteModal = useCallback(async (q: Question) => {
    setTargetQuestionId(q.id);
    setPreview(null); setModalOpen(true); setPreviewLoading(true);
    try {
      const rid = await resolveReportId(q);
      if (!rid) {
        setModalOpen(false);
        Modal.confirm({
          title: "删除此记录？",
          content: "该任务已完成但未找到关联报告，将直接清理数据库记录。",
          okText: "删除", cancelText: "取消",
          okButtonProps: { danger: true },
          onOk: () => deleteQuestion(q.id),
        });
        return;
      }
      setTargetReportId(rid);
      const res = await apiClient.get<DeletePreview>(`/api/reports/${rid}/delete-preview`);
      setPreview(res.data);
    } catch {
      message.error("获取删除预览失败"); setModalOpen(false);
    } finally {
      setPreviewLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const confirmDelete = async () => {
    if (!targetReportId) return;
    setDeleting(true);
    try {
      await apiClient.delete(`/api/reports/${targetReportId}`);
      setQuestions(qs => qs.filter(q => q.id !== targetQuestionId));
      message.success("报告及关联文件已删除"); setModalOpen(false);
    } catch { message.error("删除失败"); }
    finally { setDeleting(false); }
  };

  const deleteQuestion = async (questionId: number) => {
    try {
      await apiClient.delete(`/api/questions/${questionId}`);
      setQuestions(qs => qs.filter(q => q.id !== questionId));
      message.success("记录已删除");
    } catch { message.error("删除失败"); }
  };

  // 搜索过滤 + 分组（admin 按用户分组，普通用户按日期分组）
  const grouped = useMemo(() => {
    const kw = searchText.trim().toLowerCase();
    const filtered = kw
      ? questions.filter(q => q.raw_text.toLowerCase().includes(kw))
      : questions;

    if (isAdmin) {
      // admin: 先按用户分组，组内按时间倒序（API 已按时间倒序返回，保持即可）
      const map = new Map<string, Question[]>();
      for (const q of filtered) {
        const key = q.user_name ?? "未知用户";
        if (!map.has(key)) map.set(key, []);
        map.get(key)!.push(q);
      }
      // 按每组最新一条时间倒序排用户
      return [...map.entries()]
        .sort((a, b) => {
          const ta = a[1][0]?.created_at ?? "";
          const tb = b[1][0]?.created_at ?? "";
          return tb.localeCompare(ta);
        })
        .map(([label, items]) => ({ label, items, isUser: true }));
    }

    const map = new Map<string, Question[]>();
    for (const q of filtered) {
      const g = getDateGroup(q.created_at);
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(q);
    }
    // 排序：今天/昨天/本周在前，然后月份/年份倒序
    const keys = [...map.keys()].sort((a, b) => {
      const ai = GROUP_ORDER.indexOf(a);
      const bi = GROUP_ORDER.indexOf(b);
      if (ai !== -1 && bi !== -1) return ai - bi;
      if (ai !== -1) return -1;
      if (bi !== -1) return 1;
      return b.localeCompare(a);
    });
    return keys.map(k => ({ label: k, items: map.get(k)!, isUser: false }));
  }, [questions, searchText, isAdmin]);

  const totalFiltered = grouped.reduce((s, g) => s + g.items.length, 0);

  const USERS_PER_PAGE = 5;
  // 页码存进 URL（?p=2），从报告页返回时能恢复到原来的分页
  const [searchParams, setSearchParams] = useSearchParams();
  const userPage = Math.max(1, parseInt(searchParams.get("p") ?? "1", 10) || 1);
  const setUserPage = useCallback((p: number | ((prev: number) => number)) => {
    setSearchParams(prev => {
      const cur = Math.max(1, parseInt(prev.get("p") ?? "1", 10) || 1);
      const next = typeof p === "function" ? p(cur) : p;
      const sp = new URLSearchParams(prev);
      if (next <= 1) sp.delete("p"); else sp.set("p", String(next));
      return sp;
    }, { replace: true });
  }, [setSearchParams]);

  const pagedGroups = useMemo(() => {
    if (!isAdmin) return grouped;
    const userGroups = grouped.filter(g => g.isUser);
    const start = (userPage - 1) * USERS_PER_PAGE;
    return userGroups.slice(start, start + USERS_PER_PAGE);
  }, [grouped, isAdmin, userPage]);

  const totalUserGroups = isAdmin ? grouped.filter(g => g.isUser).length : 0;

  const approvedDocs = preview?.documents.filter(d => d.target_exists) ?? [];
  const stagingDocs  = preview?.documents.filter(d => d.staging_exists && !d.target_exists) ?? [];

  return (
    <div style={{ maxWidth: 720, margin: "0 auto", padding: "40px 20px 60px" }}>
      {/* header */}
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", marginBottom: 20 }}>
        <div>
          <h1 style={{ fontSize: 22, fontWeight: 800, color: "#0f172a", margin: 0, letterSpacing: "-0.4px" }}>
            {isAdmin ? "全部提问" : "我的提问"}
          </h1>
          <p style={{ fontSize: 13.5, color: "#94a3b8", marginTop: 4, marginBottom: 0 }}>
            {isAdmin ? "按用户分组，点击记录查看详情" : "点击记录查看对话详情与流水线进度"}
          </p>
        </div>
        <button
          onClick={() => navigate("/ask")}
          style={{
            display: "flex", alignItems: "center", gap: 7,
            background: "linear-gradient(135deg, #1e3a5f, #2563eb)",
            color: "#fff", fontSize: 13.5, fontWeight: 700,
            padding: "9px 18px", borderRadius: 12, border: "none", cursor: "pointer",
            boxShadow: "0 4px 12px rgba(37,99,235,0.3)",
            transition: "all 0.2s ease",
          }}
          onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(37,99,235,0.4)"; }}
          onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(37,99,235,0.3)"; }}
        >
          <PlusOutlined style={{ fontSize: 12 }} />
          新建提问
        </button>
      </div>

      {/* search bar */}
      {!loading && questions.length > 0 && (
        <div style={{ marginBottom: 24 }}>
          <Input
            prefix={<SearchOutlined style={{ color: "#94a3b8" }} />}
            placeholder="搜索提问内容…"
            value={searchText}
            onChange={e => { setSearchText(e.target.value); setUserPage(1); }}
            allowClear
            style={{
              borderRadius: 10, height: 38,
              background: "rgba(255,255,255,0.85)",
              boxShadow: "0 1px 4px rgba(0,0,0,0.06)",
            }}
          />
          {searchText && (
            <p style={{ fontSize: 12, color: "#94a3b8", marginTop: 6, marginBottom: 0 }}>
              找到 {totalFiltered} 条结果
            </p>
          )}
        </div>
      )}

      {/* list */}
      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", padding: "64px 0" }}><Spin /></div>
      ) : questions.length === 0 ? (
        <EmptyState onNew={() => navigate("/ask")} />
      ) : totalFiltered === 0 ? (
        <div style={{ textAlign: "center", padding: "48px 0", color: "#94a3b8", fontSize: 14 }}>
          没有匹配「{searchText}」的提问
        </div>
      ) : (
        <>
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            {pagedGroups.map(({ label, items, isUser }) => (
              isUser ? (
                <CollapsibleGroup
                  key={label}
                  label={label}
                  count={items.length}
                >
                  {items.map((q, idx) => (
                    <QuestionCard
                      key={q.id}
                      q={q}
                      idx={idx}
                      searchText={searchText}
                      showUser={true}
                      onNavigate={async () => {
                        if (q.status === "done") {
                          const rid = await resolveReportId(q);
                          if (rid) { navigate(`/reports/${rid}`); return; }
                        }
                        navigate(`/ask/${q.id}`);
                      }}
                      onViewReport={async () => {
                        const rid = await resolveReportId(q);
                        if (rid) navigate(`/reports/${rid}`);
                        else message.error("未找到报告");
                      }}
                      onDelete={() => openDeleteModal(q)}
                    />
                  ))}
                </CollapsibleGroup>
              ) : (
                <div key={label}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
                    <span style={{ fontSize: 12, fontWeight: 700, color: "#64748b", letterSpacing: "0.04em" }}>
                      {label}
                    </span>
                    <span style={{
                      fontSize: 11, fontWeight: 600, color: "#94a3b8",
                      background: "#f1f5f9", borderRadius: 10, padding: "1px 7px",
                    }}>
                      {items.length}
                    </span>
                    <div style={{ flex: 1, height: 1, background: "#e2e8f0" }} />
                  </div>
                  <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                    {items.map((q, idx) => (
                      <QuestionCard
                        key={q.id}
                        q={q}
                        idx={idx}
                        searchText={searchText}
                        showUser={false}
                        onNavigate={async () => {
                          if (q.status === "done") {
                            const rid = await resolveReportId(q);
                            if (rid) { navigate(`/reports/${rid}`); return; }
                          }
                          navigate(`/ask/${q.id}`);
                        }}
                        onViewReport={async () => {
                          const rid = await resolveReportId(q);
                          if (rid) navigate(`/reports/${rid}`);
                          else message.error("未找到报告");
                        }}
                        onDelete={() => openDeleteModal(q)}
                      />
                    ))}
                  </div>
                </div>
              )
            ))}
          </div>

          {/* admin 用户组分页器 */}
          {isAdmin && totalUserGroups > USERS_PER_PAGE && (
            <div style={{ display: "flex", justifyContent: "center", alignItems: "center", gap: 8, marginTop: 28 }}>
              <button
                disabled={userPage === 1}
                onClick={() => setUserPage(p => p - 1)}
                style={{
                  padding: "6px 14px", borderRadius: 8, border: "1px solid #e2e8f0",
                  background: userPage === 1 ? "#f8fafc" : "#fff",
                  color: userPage === 1 ? "#cbd5e1" : "#374151",
                  cursor: userPage === 1 ? "not-allowed" : "pointer",
                  fontSize: 13, fontWeight: 600, transition: "all 0.15s",
                }}
              >← 上一页</button>

              {Array.from({ length: Math.ceil(totalUserGroups / USERS_PER_PAGE) }, (_, i) => i + 1).map(p => (
                <button
                  key={p}
                  onClick={() => setUserPage(p)}
                  style={{
                    width: 32, height: 32, borderRadius: 8,
                    border: p === userPage ? "1.5px solid #3b82f6" : "1px solid #e2e8f0",
                    background: p === userPage ? "#eff6ff" : "#fff",
                    color: p === userPage ? "#2563eb" : "#374151",
                    cursor: "pointer", fontSize: 13, fontWeight: p === userPage ? 700 : 500,
                    transition: "all 0.15s",
                  }}
                >{p}</button>
              ))}

              <button
                disabled={userPage >= Math.ceil(totalUserGroups / USERS_PER_PAGE)}
                onClick={() => setUserPage(p => p + 1)}
                style={{
                  padding: "6px 14px", borderRadius: 8, border: "1px solid #e2e8f0",
                  background: userPage >= Math.ceil(totalUserGroups / USERS_PER_PAGE) ? "#f8fafc" : "#fff",
                  color: userPage >= Math.ceil(totalUserGroups / USERS_PER_PAGE) ? "#cbd5e1" : "#374151",
                  cursor: userPage >= Math.ceil(totalUserGroups / USERS_PER_PAGE) ? "not-allowed" : "pointer",
                  fontSize: 13, fontWeight: 600, transition: "all 0.15s",
                }}
              >下一页 →</button>
            </div>
          )}
        </>
      )}

      {/* delete modal */}
      <Modal
        title={<span style={{ fontWeight: 700, color: "#0f172a" }}>确认删除报告</span>}
        open={modalOpen}
        onCancel={() => !deleting && setModalOpen(false)}
        onOk={confirmDelete}
        okText="确认删除" cancelText="取消"
        okButtonProps={{ danger: true, loading: deleting }}
        cancelButtonProps={{ disabled: deleting }}
        width={540}
      >
        {previewLoading ? (
          <div style={{ display: "flex", justifyContent: "center", padding: "32px 0" }}>
            <Spin tip="正在计算影响范围..." />
          </div>
        ) : preview ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 14, marginTop: 8 }}>
            <Alert type="warning" showIcon message="以下内容将被永久删除，无法恢复" />

            <div>
              <p style={{ fontSize: 12.5, fontWeight: 600, color: "#475569", marginBottom: 6 }}>报告文件</p>
              <div style={{ background: "#f8fafc", borderRadius: 10, padding: "10px 14px", fontSize: 12, color: "#475569", fontFamily: "monospace", wordBreak: "break-all", border: "1px solid #e2e8f0" }}>
                {preview.report.path}
                {!preview.report.exists && <span style={{ marginLeft: 8, color: "#94a3b8" }}>(文件不存在)</span>}
              </div>
            </div>

            {preview.qa_files.length > 0 && (
              <div>
                <p style={{ fontSize: 12.5, fontWeight: 600, color: "#475569", marginBottom: 6 }}>问答存档（{preview.qa_files.length} 项）</p>
                <div style={{ background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0", maxHeight: 120, overflowY: "auto" }}>
                  {preview.qa_files.map(p => (
                    <div key={p} style={{ padding: "6px 14px", fontSize: 12, color: "#64748b", fontFamily: "monospace", borderBottom: "1px solid #f1f5f9", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p}</div>
                  ))}
                </div>
              </div>
            )}

            {stagingDocs.length > 0 && (
              <div>
                <p style={{ fontSize: 12.5, fontWeight: 600, color: "#475569", marginBottom: 6 }}>暂存文件（{stagingDocs.length} 项，未入库，将一并删除）</p>
                <div style={{ background: "#f8fafc", borderRadius: 10, border: "1px solid #e2e8f0", maxHeight: 120, overflowY: "auto" }}>
                  {stagingDocs.map(d => (
                    <div key={d.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 14px", borderBottom: "1px solid #f1f5f9" }}>
                      <span style={{ fontSize: 10, background: "#fed7aa", color: "#c2410c", padding: "1px 6px", borderRadius: 4, fontWeight: 700, flexShrink: 0, marginTop: 2 }}>{SOURCE_LABEL[d.source] ?? d.source}</span>
                      <span style={{ fontSize: 12, color: "#475569" }}>{d.title}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {approvedDocs.length > 0 && (
              <div>
                <p style={{ fontSize: 12.5, fontWeight: 600, color: "#475569", marginBottom: 6 }}>
                  已入库文件（{approvedDocs.length} 项）
                  <span style={{ fontWeight: 400, color: "#94a3b8", marginLeft: 6 }}>— 已在知识库中，不会删除</span>
                </p>
                <div style={{ background: "#f0fdf4", borderRadius: 10, border: "1px solid #bbf7d0", maxHeight: 160, overflowY: "auto" }}>
                  {approvedDocs.map(d => (
                    <div key={d.id} style={{ display: "flex", alignItems: "flex-start", gap: 8, padding: "8px 14px", borderBottom: "1px solid #dcfce7" }}>
                      <span style={{ fontSize: 10, background: "#dbeafe", color: "#1d4ed8", padding: "1px 6px", borderRadius: 4, fontWeight: 700, flexShrink: 0, marginTop: 2 }}>{SOURCE_LABEL[d.source] ?? d.source}</span>
                      <span style={{ fontSize: 12, color: "#475569" }}>{d.title}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {preview.documents.length === 0 && (
              <p style={{ fontSize: 13, color: "#94a3b8" }}>无关联文档记录</p>
            )}
          </div>
        ) : null}
      </Modal>

      <style>{`
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(10px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse {
          0%, 100% { box-shadow: 0 0 0 3px rgba(59,130,246,0.2); }
          50%       { box-shadow: 0 0 0 5px rgba(59,130,246,0.12); }
        }
      `}</style>
    </div>
  );
}

// ── 可折叠用户分组 ────────────────────────────────────────

function CollapsibleGroup({
  label, count, children,
}: {
  label: string; count: number; children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div style={{
      border: "1px solid #e2e8f0", borderRadius: 14,
      overflow: "hidden", background: "rgba(255,255,255,0.6)",
    }}>
      {/* header */}
      <div
        onClick={() => setOpen(o => !o)}
        style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px", cursor: "pointer",
          background: open ? "rgba(239,246,255,0.7)" : "#f8fafc",
          borderBottom: open ? "1px solid #e2e8f0" : "none",
          transition: "background 0.15s",
          userSelect: "none",
        }}
      >
        <span style={{
          width: 22, height: 22, borderRadius: "50%", flexShrink: 0,
          background: "linear-gradient(135deg, #dbeafe, #ede9fe)",
          border: "1px solid #bfdbfe",
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          <UserOutlined style={{ fontSize: 11, color: "#4f46e5" }} />
        </span>
        <span style={{ fontSize: 13, fontWeight: 700, color: "#1e3a5f", flex: 1 }}>{label}</span>
        <span style={{
          fontSize: 11, fontWeight: 600, color: "#94a3b8",
          background: "#f1f5f9", borderRadius: 10, padding: "1px 7px",
        }}>{count}</span>
        <span style={{
          fontSize: 11, color: "#94a3b8",
          transform: open ? "rotate(90deg)" : "rotate(0deg)",
          transition: "transform 0.2s",
          display: "inline-block",
        }}>▶</span>
      </div>
      {/* body */}
      {open && (
        <div style={{ display: "flex", flexDirection: "column", gap: 1, padding: "8px 10px", background: "transparent" }}>
          {children}
        </div>
      )}
    </div>
  );
}

// ── 单张卡片 ──────────────────────────────────────────────

function highlight(text: string, kw: string) {
  if (!kw) return <>{text}</>;
  const idx = text.toLowerCase().indexOf(kw.toLowerCase());
  if (idx === -1) return <>{text}</>;
  return (
    <>
      {text.slice(0, idx)}
      <mark style={{ background: "#fef08a", borderRadius: 2, padding: "0 1px" }}>
        {text.slice(idx, idx + kw.length)}
      </mark>
      {text.slice(idx + kw.length)}
    </>
  );
}

function QuestionCard({
  q, idx, searchText, showUser,
  onNavigate, onViewReport, onDelete,
}: {
  q: Question; idx: number; searchText: string; showUser: boolean;
  onNavigate: () => void;
  onViewReport: () => void;
  onDelete: () => void;
}) {
  const isActive = !["done", "failed", "cancelled"].includes(q.status);
  const tier = TIER_CONFIG[q.tier] ?? TIER_CONFIG.normal;
  const statusCfg = STATUS_CONFIG[q.status] ?? STATUS_CONFIG.running;

  const date = new Date(q.created_at);
  const timeStr = `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
  const dateStr = showUser
    ? `${date.getMonth() + 1}/${date.getDate()} ${timeStr}`
    : timeStr;

  return (
    <div
      className="sessions-card"
      onClick={onNavigate}
      style={{
        background: "rgba(255,255,255,0.85)",
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
        border: "1px solid rgba(226,232,240,0.8)",
        borderRadius: 14,
        display: "flex", alignItems: "stretch",
        cursor: "pointer",
        transition: "all 0.18s ease",
        boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
        animation: `fadeUp 0.3s ${idx * 0.04}s cubic-bezier(0.16,1,0.3,1) both`,
        overflow: "hidden",
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = "#93c5fd";
        e.currentTarget.style.boxShadow = "0 4px 16px rgba(37,99,235,0.1), 0 1px 4px rgba(0,0,0,0.06)";
        e.currentTarget.style.transform = "translateY(-1px)";
        const del = e.currentTarget.querySelector<HTMLElement>(".del-btn");
        if (del) del.style.opacity = "1";
        const arrow = e.currentTarget.querySelector<HTMLElement>(".arrow-icon");
        if (arrow) arrow.style.color = "#93c5fd";
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = "rgba(226,232,240,0.8)";
        e.currentTarget.style.boxShadow = "0 1px 3px rgba(0,0,0,0.04)";
        e.currentTarget.style.transform = "translateY(0)";
        const del = e.currentTarget.querySelector<HTMLElement>(".del-btn");
        if (del) del.style.opacity = "0";
        const arrow = e.currentTarget.querySelector<HTMLElement>(".arrow-icon");
        if (arrow) arrow.style.color = "#e2e8f0";
      }}
    >
      {/* left accent bar */}
      <div style={{
        width: 4, flexShrink: 0,
        background: statusCfg.dot,
        opacity: q.status === "cancelled" ? 0.35 : 0.8,
      }} />

      {/* card body */}
      <div style={{ flex: 1, minWidth: 0, display: "flex", alignItems: "center", gap: 12, padding: "13px 16px" }}>
        {/* status icon */}
        <div style={{
          width: 36, height: 36, borderRadius: 10, flexShrink: 0,
          background: statusCfg.bg, border: `1px solid ${statusCfg.border}`,
          display: "flex", alignItems: "center", justifyContent: "center",
        }}>
          {q.status === "done"
            ? <CheckCircleFilled style={{ fontSize: 17, color: "#10b981" }} />
            : q.status === "failed"
              ? <ExclamationCircleFilled style={{ fontSize: 17, color: "#ef4444" }} />
              : q.status === "cancelled"
                ? <StopOutlined style={{ fontSize: 14, color: "#9ca3af" }} />
                : <span style={{ width: 9, height: 9, borderRadius: "50%", background: "#3b82f6", display: "block",
                    boxShadow: "0 0 0 3px rgba(59,130,246,0.2)", animation: "pulse 2s infinite" }} />
          }
        </div>

        {/* text */}
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={{
            fontSize: 14, fontWeight: 600, color: "#0f172a",
            margin: "0 0 5px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {highlight(q.raw_text, searchText)}
          </p>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 5 }}>
            <StatusBadge status={q.status} />
            {q.tier !== "normal" && (
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 3,
                fontSize: 11, fontWeight: 600, padding: "2px 7px",
                borderRadius: 20, border: `1px solid ${tier.border}`,
                background: tier.bg, color: tier.color,
              }}>
                <span style={{ fontSize: 10 }}>{tier.icon}</span>
                {tier.label}
              </span>
            )}
            <span style={{ display: "flex", alignItems: "center", gap: 3, fontSize: 11, color: "#94a3b8" }}>
              <ClockCircleOutlined style={{ fontSize: 10 }} /> {dateStr}
            </span>
          </div>
        </div>

        {/* right actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 5, flexShrink: 0 }}
          onClick={e => e.stopPropagation()}>
          {q.status === "done" && (
            <>
              <button
                onClick={onViewReport}
                style={{
                  display: "flex", alignItems: "center", gap: 5,
                  fontSize: 12, fontWeight: 600, color: "#2563eb",
                  background: "#eff6ff", border: "1px solid #bfdbfe",
                  padding: "5px 10px", borderRadius: 8, cursor: "pointer",
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "#dbeafe"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "#eff6ff"; }}
              >
                <FileTextOutlined style={{ fontSize: 11 }} /> 查看报告
              </button>
              <button
                className="del-btn"
                onClick={onDelete}
                style={{
                  width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                  borderRadius: 7, border: "none", cursor: "pointer",
                  background: "transparent", color: "#cbd5e1", opacity: 0,
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={e => { e.currentTarget.style.color = "#ef4444"; e.currentTarget.style.background = "#fef2f2"; }}
                onMouseLeave={e => { e.currentTarget.style.color = "#cbd5e1"; e.currentTarget.style.background = "transparent"; }}
              >
                <DeleteOutlined style={{ fontSize: 12 }} />
              </button>
            </>
          )}
          {!isActive && q.status !== "done" && (
            <Popconfirm
              title="删除此记录？"
              description="将清理暂存文件及数据库记录。"
              okText="删除" cancelText="取消"
              okButtonProps={{ danger: true }}
              onConfirm={onDelete}
            >
              <button
                className="del-btn"
                onClick={e => e.stopPropagation()}
                style={{
                  width: 28, height: 28, display: "flex", alignItems: "center", justifyContent: "center",
                  borderRadius: 7, border: "none", cursor: "pointer",
                  background: "transparent", color: "#cbd5e1", opacity: 0,
                  transition: "all 0.15s ease",
                }}
                onMouseEnter={e => { e.currentTarget.style.color = "#ef4444"; e.currentTarget.style.background = "#fef2f2"; }}
                onMouseLeave={e => { e.currentTarget.style.color = "#cbd5e1"; e.currentTarget.style.background = "transparent"; }}
              >
                <DeleteOutlined style={{ fontSize: 12 }} />
              </button>
            </Popconfirm>
          )}
          <RightOutlined className="arrow-icon" style={{ fontSize: 11, color: "#e2e8f0", transition: "color 0.15s ease" }} />
        </div>
      </div>
    </div>
  );
}

// ── 空状态 ──────────────────────────────────────────────

function EmptyState({ onNew }: { onNew: () => void }) {
  return (
    <div style={{ textAlign: "center", padding: "72px 0 48px" }}>
      <div style={{ position: "relative", display: "inline-block", marginBottom: 24 }}>
        <div style={{
          position: "absolute", inset: -20, borderRadius: "50%",
          background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)",
          pointerEvents: "none",
        }} />
        <div style={{
          width: 72, height: 72, borderRadius: 22,
          background: "linear-gradient(135deg, #eff6ff 0%, #dbeafe 100%)",
          border: "1.5px solid #bfdbfe",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 8px 24px rgba(59,130,246,0.12)",
          position: "relative",
        }}>
          <svg width="30" height="30" viewBox="0 0 30 30" fill="none" aria-hidden="true">
            <path d="M6 8a2 2 0 012-2h14a2 2 0 012 2v16a2 2 0 01-2 2H8a2 2 0 01-2-2V8z" fill="#dbeafe" stroke="#3b82f6" strokeWidth="1.5"/>
            <path d="M10 13h10M10 17h7" stroke="#60a5fa" strokeWidth="1.5" strokeLinecap="round"/>
            <circle cx="22" cy="9" r="4.5" fill="#2563eb"/>
            <path d="M20.5 9l1 1 2-2" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </div>
        <div style={{
          position: "absolute", top: -10, right: -22,
          background: "#fff", border: "1px solid #e0e7ff",
          borderRadius: 8, padding: "3px 7px",
          fontSize: 10, color: "#6366f1", fontWeight: 600,
          boxShadow: "0 2px 8px rgba(99,102,241,0.1)",
          display: "flex", alignItems: "center", gap: 3, whiteSpace: "nowrap",
        }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#818cf8", display: "inline-block" }} />
          AI 调研
        </div>
        <div style={{
          position: "absolute", bottom: -8, left: -24,
          background: "#fff", border: "1px solid #dcfce7",
          borderRadius: 8, padding: "3px 7px",
          fontSize: 10, color: "#16a34a", fontWeight: 600,
          boxShadow: "0 2px 8px rgba(34,197,94,0.1)",
          display: "flex", alignItems: "center", gap: 3, whiteSpace: "nowrap",
        }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: "#4ade80", display: "inline-block" }} />
          报告生成
        </div>
      </div>
      <p style={{ color: "#1e3a5f", fontWeight: 700, fontSize: 16, margin: "0 0 8px" }}>还没有提问记录</p>
      <p style={{ color: "#94a3b8", fontSize: 13.5, margin: "0 0 22px", lineHeight: 1.6 }}>
        向 MRA 提交市场研究问题<br/>整合内部知识与实时情报 · 生成可追溯报告
      </p>
      <button onClick={onNew}
        style={{
          display: "inline-flex", alignItems: "center", gap: 7,
          fontSize: 13.5, fontWeight: 600, color: "#fff",
          background: "linear-gradient(135deg, #3b82f6 0%, #6366f1 100%)",
          border: "none", borderRadius: 10, cursor: "pointer",
          padding: "9px 20px",
          boxShadow: "0 4px 12px rgba(59,130,246,0.35)",
          transition: "all 0.18s ease",
        }}
        onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.boxShadow = "0 6px 18px rgba(59,130,246,0.45)"; }}
        onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "0 4px 12px rgba(59,130,246,0.35)"; }}
      >
        <PlusOutlined style={{ fontSize: 13 }} />
        开始第一次提问
      </button>
    </div>
  );
}
