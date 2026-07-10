import { useEffect, useState, useCallback } from "react";
import { Table, Input, Button, Tag, Space, Typography, Popconfirm, message, Select } from "antd";
import type { ColumnsType } from "antd/es/table";
import { SearchOutlined, UserOutlined, CrownOutlined, DeleteOutlined } from "@ant-design/icons";
import { apiClient } from "@/api/client";
import { useAuth } from "@/contexts/AuthContext";

const { Title } = Typography;

interface UserItem {
  id: number;
  name: string;
  feishu_user_id: string;
  role: "user" | "admin";
  avatar_url: string | null;
  created_at: string | null;
}

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<UserItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(false);

  const fetchUsers = useCallback(() => {
    setLoading(true);
    apiClient
      .get("/api/admin/users", { params: { page, page_size: pageSize, search } })
      .then((res) => {
        setUsers(res.data.items);
        setTotal(res.data.total);
      })
      .catch(() => message.error("加载失败"))
      .finally(() => setLoading(false));
  }, [page, pageSize, search]);

  useEffect(() => { fetchUsers(); }, [fetchUsers]);

  async function handleRoleChange(userId: number, role: "user" | "admin") {
    try {
      await apiClient.patch(`/api/admin/users/${userId}/role`, { role });
      message.success(role === "admin" ? "已提升为管理员" : "已降级为普通用户");
      fetchUsers();
    } catch {
      message.error("操作失败");
    }
  }

  async function handleDelete(userId: number) {
    try {
      await apiClient.delete(`/api/admin/users/${userId}`);
      message.success("已删除");
      fetchUsers();
    } catch {
      message.error("删除失败");
    }
  }

  const columns: ColumnsType<UserItem> = [
    {
      title: "用户",
      key: "user",
      render: (_, r) => (
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
            background: r.role === "admin"
              ? "linear-gradient(135deg, #6366f1 0%, #4f46e5 100%)"
              : "linear-gradient(135deg, #64748b 0%, #475569 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            boxShadow: "0 2px 6px rgba(0,0,0,0.12)",
          }}>
            <span style={{ color: "#fff", fontSize: 14, fontWeight: 700 }}>
              {r.name?.[0]?.toUpperCase() ?? "U"}
            </span>
          </div>
          <div>
            <div style={{ fontWeight: 600, fontSize: 14, color: "#1e293b" }}>{r.name}</div>
            <div style={{ fontSize: 12, color: "#94a3b8", marginTop: 1 }}>{r.feishu_user_id}</div>
          </div>
        </div>
      ),
    },
    {
      title: "角色",
      dataIndex: "role",
      width: 100,
      render: (role) =>
        role === "admin" ? (
          <Tag icon={<CrownOutlined />} color="purple">管理员</Tag>
        ) : (
          <Tag icon={<UserOutlined />} color="default">普通用户</Tag>
        ),
    },
    {
      title: "注册时间",
      dataIndex: "created_at",
      width: 160,
      render: (v) =>
        v ? new Date(v).toLocaleString("zh-CN", { year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—",
    },
    {
      title: "操作",
      key: "action",
      width: 180,
      render: (_, r) => {
        const isSelf = r.id === me?.id;
        return (
          <Space>
            <Select
              size="small"
              value={r.role}
              disabled={isSelf}
              style={{ width: 110 }}
              onChange={(val) => handleRoleChange(r.id, val)}
              options={[
                { value: "user", label: "普通用户" },
                { value: "admin", label: "管理员" },
              ]}
            />
            <Popconfirm
              title="确认删除该用户？"
              description="删除后无法恢复"
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
              disabled={isSelf}
              onConfirm={() => handleDelete(r.id)}
            >
              <Button
                size="small"
                danger
                icon={<DeleteOutlined />}
                disabled={isSelf}
              />
            </Popconfirm>
          </Space>
        );
      },
    },
  ];

  return (
    <div style={{ maxWidth: 900, margin: "0 auto", padding: "32px 24px" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 24 }}>
        <Title level={4} style={{ margin: 0 }}>用户管理</Title>
        <span style={{ fontSize: 13, color: "#64748b" }}>共 {total} 位用户</span>
      </div>

      <div style={{ marginBottom: 16 }}>
        <Input
          prefix={<SearchOutlined style={{ color: "#94a3b8" }} />}
          placeholder="搜索用户名或飞书 ID"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onPressEnter={() => { setPage(1); setSearch(searchInput); }}
          allowClear
          onClear={() => { setSearchInput(""); setSearch(""); setPage(1); }}
          style={{ width: 280 }}
          suffix={
            <Button
              type="text"
              size="small"
              style={{ color: "#6366f1", padding: "0 4px" }}
              onClick={() => { setPage(1); setSearch(searchInput); }}
            >
              搜索
            </Button>
          }
        />
      </div>

      <div style={{
        background: "rgba(255,255,255,0.85)",
        borderRadius: 16,
        boxShadow: "0 2px 12px rgba(0,0,0,0.07)",
        overflow: "hidden",
      }}>
        <Table<UserItem>
          rowKey="id"
          columns={columns}
          dataSource={users}
          loading={loading}
          pagination={{
            current: page,
            pageSize,
            total,
            showSizeChanger: true,
            pageSizeOptions: ["10", "20", "50"],
            showTotal: (t) => `共 ${t} 条`,
            onChange: (p, ps) => { setPage(p); setPageSize(ps); },
          }}
          rowClassName={(r) => (r.id === me?.id ? "row-self" : "")}
        />
      </div>

      <style>{`
        .row-self td { background: rgba(99,102,241,0.04) !important; }
      `}</style>
    </div>
  );
}
