import { useEffect, useState, useCallback } from "react";
import { Table, Button, Tag, Space, Typography, message, Drawer, Spin, Descriptions, Collapse, Badge, Alert } from "antd";
import type { ColumnsType } from "antd/es/table";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { apiClient } from "@/api/client";

const { Title, Text } = Typography;

interface PendingDoc {
  id: number;
  task_id: number;
  question_text: string;
  source: string;
  title: string;
  status: string;
  created_at: string;
  authors?: string;
  year?: string;
  venue?: string;
  doi?: string;
  abstract?: string;
  ipc?: string;
  core_innovation?: string;
}

const sourceLabel: Record<string, string> = { ieee: "IEEE论文", patent: "专利", web: "Web" };
const sourceColor: Record<string, string> = { ieee: "blue", patent: "purple", web: "cyan" };

export default function DocumentReview() {
  const [docs, setDocs] = useState<PendingDoc[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Record<number, number[]>>({});

  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerDoc, setDrawerDoc] = useState<PendingDoc | null>(null);
  const [drawerContent, setDrawerContent] = useState("");
  const [drawerFileDir, setDrawerFileDir] = useState("");
  const [drawerLoading, setDrawerLoading] = useState(false);

  function fetchDocs() {
    setLoading(true);
    apiClient
      .get<PendingDoc[]>("/api/pending-docs")
      .then((res) => setDocs(res.data))
      .finally(() => setLoading(false));
  }

  useEffect(fetchDocs, []);

  async function handleAction(action: "approve" | "reject", ids: number[]) {
    if (ids.length === 1) {
      await apiClient.post(`/api/pending-docs/${ids[0]}/${action}`);
    } else {
      await apiClient.post("/api/pending-docs/batch", { action, ids });
    }
    message.success(action === "approve" ? "已批准入库" : "已拒绝");
    setSelectedIds({});
    fetchDocs();
    window.dispatchEvent(new Event("pending-docs-changed"));
  }

  const openPreview = useCallback(async (doc: PendingDoc) => {
    setDrawerDoc(doc);
    setDrawerContent("");
    setDrawerFileDir("");
    setDrawerOpen(true);
    setDrawerLoading(true);
    try {
      const res = await apiClient.get<string>(`/api/pending-docs/${doc.id}/preview`, { responseType: "text" });
      setDrawerContent(typeof res.data === "string" ? res.data : "");
      setDrawerFileDir(res.headers?.["x-file-dir"] ?? "");
    } catch {
      setDrawerContent("*无法加载文档内容*");
    } finally {
      setDrawerLoading(false);
    }
  }, []);

  // Group docs by task_id, preserving insertion order
  const taskGroups: { task_id: number; question_text: string; docs: PendingDoc[] }[] = [];
  const taskIndex: Record<number, number> = {};
  for (const doc of docs) {
    if (taskIndex[doc.task_id] === undefined) {
      taskIndex[doc.task_id] = taskGroups.length;
      taskGroups.push({ task_id: doc.task_id, question_text: doc.question_text, docs: [] });
    }
    taskGroups[taskIndex[doc.task_id]].docs.push(doc);
  }

  const allSelectedIds = Object.values(selectedIds).flat();

  function columns(): ColumnsType<PendingDoc> {
    return [
      {
        title: "标题 / 作者 / 年份",
        dataIndex: "title",
        render: (_, record) => (
          <div>
            <div style={{ fontWeight: 500, marginBottom: 2 }}>{record.title}</div>
            <div style={{ fontSize: 12, color: "#888" }}>
              {[record.authors, record.year, record.venue].filter(Boolean).join("  ·  ")}
            </div>
            {record.core_innovation && (
              <div style={{ fontSize: 12, color: "#555", marginTop: 2, fontStyle: "italic" }}>
                {record.core_innovation.slice(0, 80)}{record.core_innovation.length > 80 ? "…" : ""}
              </div>
            )}
          </div>
        ),
      },
      {
        title: "来源",
        dataIndex: "source",
        width: 90,
        render: (s: string) => <Tag color={sourceColor[s] ?? "default"}>{sourceLabel[s] ?? s}</Tag>,
      },
      {
        title: "操作",
        width: 200,
        render: (_, record) => (
          <Space>
            <Button size="small" onClick={() => openPreview(record)}>预览</Button>
            {record.status === "pending" && (
              <>
                <Button size="small" type="primary" onClick={() => handleAction("approve", [record.id])}>批准</Button>
                <Button size="small" danger onClick={() => handleAction("reject", [record.id])}>拒绝</Button>
              </>
            )}
          </Space>
        ),
      },
    ];
  }

  const collapseItems = taskGroups.map((group) => {
    const taskSelectedIds = selectedIds[group.task_id] ?? [];
    const pendingCount = group.docs.filter((d) => d.status === "pending").length;
    return {
      key: String(group.task_id),
      label: (
        <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
          <Badge count={pendingCount} style={{ backgroundColor: "#1677ff", flexShrink: 0 }} />
          <span style={{ fontWeight: 500, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {group.question_text}
          </span>
          {taskSelectedIds.length > 0 && (
            <Space onClick={(e) => e.stopPropagation()}>
              <Button size="small" type="primary" onClick={() => handleAction("approve", taskSelectedIds)}>
                批量批准 ({taskSelectedIds.length})
              </Button>
              <Button size="small" danger onClick={() => handleAction("reject", taskSelectedIds)}>
                批量拒绝 ({taskSelectedIds.length})
              </Button>
            </Space>
          )}
        </div>
      ),
      children: (
        <Table
          rowKey="id"
          size="small"
          columns={columns()}
          dataSource={group.docs}
          pagination={false}
          rowSelection={{
            selectedRowKeys: taskSelectedIds,
            onChange: (keys) =>
              setSelectedIds((prev) => ({ ...prev, [group.task_id]: keys as number[] })),
            getCheckboxProps: (record) => ({ disabled: record.status !== "pending" }),
          }}
        />
      ),
    };
  });

  return (
    <div style={{ maxWidth: 1100, margin: "40px auto", padding: "0 16px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
        <Title level={3} style={{ margin: 0 }}>文档审核入库</Title>
        {allSelectedIds.length > 0 && (
          <Space>
            <Button type="primary" onClick={() => handleAction("approve", allSelectedIds)}>
              全部批准 ({allSelectedIds.length})
            </Button>
            <Button danger onClick={() => handleAction("reject", allSelectedIds)}>
              全部拒绝 ({allSelectedIds.length})
            </Button>
          </Space>
        )}
      </div>

      <Alert
        type="info"
        showIcon
        style={{ marginBottom: 20 }}
        message="为什么需要审核？"
        description={
          <ul style={{ margin: "4px 0 0", paddingLeft: 18, lineHeight: "1.9" }}>
            <li>
              <b>来源</b>：流水线远程检索（IEEE 论文、CNIPA 专利、Web 页面）获取的新文档，
              不会直接写入知识库，需管理员确认质量和相关性后才能入库。
              <i style={{ color: "#888" }}>（本次报告已直接使用这些文档，审核不影响报告结果。）</i>
            </li>
            <li>
              <b>批准后</b>：文档移入知识库正式目录（wilson_lib），
              后续任何人提问时本地搜索均可命中，知识库持续积累。
            </li>
            <li>
              <b>拒绝后</b>：文档仍保留在临时区，报告的 wikilink 仍可访问；删除报告时临时区文件一并清理，不入库。
            </li>
            <li>
              <b>超 30 天未审核（pending 状态）</b>：自动批准入库（移入 wilson_lib 正式目录）。已拒绝的文档不受此规则影响。
            </li>
          </ul>
        }
      />

      {loading ? (
        <div style={{ display: "flex", justifyContent: "center", marginTop: 80 }}>
          <Spin size="large" />
        </div>
      ) : taskGroups.length === 0 ? (
        <div style={{ textAlign: "center", padding: "80px 0 60px" }}>
          {/* 插图 */}
          <div style={{ position: "relative", display: "inline-block", marginBottom: 20 }}>
            <div style={{
              width: 72, height: 72, borderRadius: 20,
              background: "linear-gradient(135deg, #f0fdf4 0%, #dcfce7 100%)",
              border: "1px solid #bbf7d0",
              display: "flex", alignItems: "center", justifyContent: "center",
              margin: "0 auto",
              boxShadow: "0 4px 16px rgba(34,197,94,0.12)",
            }}>
              <svg width="32" height="32" viewBox="0 0 32 32" fill="none" aria-hidden="true">
                <path d="M8 10a2 2 0 012-2h12a2 2 0 012 2v14a2 2 0 01-2 2H10a2 2 0 01-2-2V10z" fill="#bbf7d0" stroke="#22c55e" strokeWidth="1.5"/>
                <path d="M12 16l3 3 5-5" stroke="#16a34a" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
                <circle cx="24" cy="10" r="5" fill="#4ade80"/>
                <path d="M22 10l1.5 1.5L26 8.5" stroke="white" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
              </svg>
            </div>
            {/* 装饰小点 */}
            <div style={{ position: "absolute", top: -4, right: -4, width: 10, height: 10, borderRadius: "50%", background: "#86efac", opacity: 0.7 }} />
            <div style={{ position: "absolute", bottom: 2, left: -6, width: 6, height: 6, borderRadius: "50%", background: "#4ade80", opacity: 0.5 }} />
          </div>
          <p style={{ color: "#15803d", fontWeight: 700, fontSize: 15, margin: "0 0 6px" }}>全部审核完毕</p>
          <p style={{ color: "#86efac", fontSize: 13, margin: 0, fontWeight: 500 }}>暂无待审核的文档，稍后再来看看</p>
        </div>
      ) : (
        <Collapse
          defaultActiveKey={taskGroups.map((g) => String(g.task_id))}
          items={collapseItems}
          style={{ background: "#fff" }}
        />
      )}

      <Drawer
        title={
          <div style={{ display: "flex", alignItems: "center", gap: 8, paddingRight: 32 }}>
            <Tag color={sourceColor[drawerDoc?.source ?? ""] ?? "default"}>
              {sourceLabel[drawerDoc?.source ?? ""] ?? drawerDoc?.source}
            </Tag>
            <Text strong style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 14 }}>
              {drawerDoc?.title}
            </Text>
            {drawerDoc?.status === "pending" && (
              <Space>
                <Button size="small" type="primary"
                  onClick={() => { handleAction("approve", [drawerDoc.id]); setDrawerOpen(false); }}>
                  批准
                </Button>
                <Button size="small" danger
                  onClick={() => { handleAction("reject", [drawerDoc.id]); setDrawerOpen(false); }}>
                  拒绝
                </Button>
              </Space>
            )}
          </div>
        }
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        width={720}
        styles={{ body: { padding: 0 }, header: { paddingRight: 48 } }}
      >
        {drawerLoading ? (
          <div style={{ display: "flex", justifyContent: "center", marginTop: 60 }}>
            <Spin />
          </div>
        ) : (
          <>
            {drawerDoc && (
              <div style={{ padding: "16px 24px", borderBottom: "1px solid #f0f0f0", background: "#fafafa" }}>
                <Descriptions size="small" column={2} styles={{ label: { color: "#999", width: 60 } }}>
                  {drawerDoc.authors && <Descriptions.Item label="作者" span={2}>{drawerDoc.authors}</Descriptions.Item>}
                  {drawerDoc.year && <Descriptions.Item label="年份">{drawerDoc.year}</Descriptions.Item>}
                  {drawerDoc.venue && <Descriptions.Item label="来源">{drawerDoc.venue}</Descriptions.Item>}
                  {drawerDoc.doi && (
                    <Descriptions.Item label="DOI" span={2}>
                      <a href={`https://doi.org/${drawerDoc.doi}`} target="_blank" rel="noopener noreferrer">{drawerDoc.doi}</a>
                    </Descriptions.Item>
                  )}
                  {drawerDoc.ipc && <Descriptions.Item label="IPC" span={2}>{drawerDoc.ipc}</Descriptions.Item>}
                  {drawerDoc.abstract && (
                    <Descriptions.Item label="摘要" span={2}>
                      <span style={{ fontSize: 12, color: "#555" }}>{drawerDoc.abstract}</span>
                    </Descriptions.Item>
                  )}
                  {drawerDoc.core_innovation && (
                    <Descriptions.Item label="核心创新" span={2}>
                      <span style={{ fontSize: 12, color: "#555" }}>{drawerDoc.core_innovation}</span>
                    </Descriptions.Item>
                  )}
                </Descriptions>
              </div>
            )}
            <div className="markdown-body" style={{ padding: "20px 24px", fontSize: 14, overflowY: "auto" }}>
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                rehypePlugins={[rehypeHighlight]}
                components={{
                  img({ src, alt, ...props }) {
                    if (!src || src.startsWith("http")) return <img src={src} alt={alt} {...props} style={{ maxWidth: "100%" }} />;
                    const rel = src.replace(/^\.?\/?/, "");
                    const base = drawerFileDir
                      ? drawerFileDir.replace(/\\/g, "/").replace(/^D:\/wilson_lib\/?/, "")
                      : "";
                    const fullPath = base ? `${base}/${rel}` : rel;
                    return (
                      <img
                        src={`/api/obsidian/img/${fullPath}?token=${localStorage.getItem("token") ?? ""}`}
                        alt={alt}
                        {...props}
                        style={{ maxWidth: "100%" }}
                      />
                    );
                  },
                }}
              >
                {drawerContent}
              </ReactMarkdown>
            </div>
          </>
        )}
      </Drawer>
    </div>
  );
}
