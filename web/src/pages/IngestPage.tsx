import { useState, useEffect, useRef, useCallback } from "react";
import { Upload, Button, Table, Tag, Progress } from "antd";import { App as AntdApp } from "antd";
import { InboxOutlined, CloudUploadOutlined, ReloadOutlined, FolderOpenOutlined } from "@ant-design/icons";
import type { UploadFile } from "antd";
import { apiClient } from "@/api/client";

const { Dragger } = Upload;

type FileRow = {
  filename: string;
  status: "queued" | "converting" | "classifying" | "done" | "failed";
  category: string;
  target_path: string;
  error: string;
  elapsed: number;
  poll_count: number;
  max_polls: number;
};

type JobResult = {
  job_id: string;
  total: number;
  done: number;
  files: FileRow[];
};

const STATUS_CFG: Record<string, { color: string; label: string }> = {
  queued:      { color: "default",    label: "等待中" },
  converting:  { color: "processing", label: "转换中" },
  classifying: { color: "processing", label: "分类中" },
  done:        { color: "success",    label: "已导入" },
  failed:      { color: "error",      label: "失败" },
};

const CATEGORY_COLORS: Record<string, string> = {
  Power:       "gold",
  ADC:         "blue",
  DAC:         "geekblue",
  Amplifier:   "purple",
  PLL:         "cyan",
  RF:          "lime",
  Patent:      "volcano",
  Others:      "default",
};

function categoryColor(cat: string) {
  return CATEGORY_COLORS[cat] ?? "blue";
}

export default function IngestPage() {
  const { message } = AntdApp.useApp();
  const [fileList, setFileList]   = useState<UploadFile[]>([]);
  const [uploading, setUploading] = useState(false);
  const [uploadedCount, setUploadedCount] = useState(0);
  const [job, setJob]             = useState<JobResult | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const uploadingRef = useRef(false);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const stopPoll = useCallback(() => {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }, []);

  const startPolling = useCallback((firstJobId: string) => {
    pollRef.current = setInterval(async () => {
      try {
        const savedIds = sessionStorage.getItem("ingest_job_ids");
        const jobIds: string[] = savedIds ? JSON.parse(savedIds) : [firstJobId];

        const results = await Promise.all(
          jobIds.map(id => apiClient.get<JobResult>(`/api/ingest/jobs/${id}`).then(r => r.data).catch(() => null))
        );
        const valid = results.filter(Boolean) as JobResult[];
        if (valid.length === 0) return;

        const submittedTotal = valid.reduce((s, j) => s + j.total, 0);
        const expectedTotal  = parseInt(sessionStorage.getItem("ingest_expected_total") || "0");
        const merged: JobResult = {
          job_id: firstJobId,
          total: Math.max(submittedTotal, expectedTotal),
          done:  valid.reduce((s, j) => s + j.done, 0),
          files: valid.flatMap(j => j.files),
        };
        setJob(merged);

        // stop only when upload is fully done AND every submitted file is converted
        if (!uploadingRef.current && merged.done === submittedTotal && submittedTotal > 0 && submittedTotal >= expectedTotal) {
          if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
          sessionStorage.removeItem("ingest_job_id");
          sessionStorage.removeItem("ingest_job_ids");
          sessionStorage.removeItem("ingest_expected_total");
          const ok   = merged.files.filter(f => f.status === "done").length;
          const fail = merged.files.filter(f => f.status === "failed").length;
          if (fail === 0) message.success(`全部 ${ok} 个文件已成功导入知识库`);
          else            message.warning(`${ok} 个成功，${fail} 个失败`);
        }
      } catch {
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
      }
    }, 2000);
  }, [message]);

  // restore active job on mount
  useEffect(() => {
    const firstId = sessionStorage.getItem("ingest_job_id");
    if (!firstId) return;

    const savedIds = sessionStorage.getItem("ingest_job_ids");
    const jobIds: string[] = savedIds ? JSON.parse(savedIds) : [firstId];

    Promise.all(
      jobIds.map(id => apiClient.get<JobResult>(`/api/ingest/jobs/${id}`).then(r => r.data).catch(() => null))
    ).then(results => {
      const valid = results.filter(Boolean) as JobResult[];
      if (valid.length === 0) { sessionStorage.removeItem("ingest_job_id"); sessionStorage.removeItem("ingest_job_ids"); sessionStorage.removeItem("ingest_expected_total"); return; }

      const submittedTotal = valid.reduce((s, j) => s + j.total, 0);
      const expectedTotal  = parseInt(sessionStorage.getItem("ingest_expected_total") || "0");
      const merged: JobResult = {
        job_id: firstId,
        total: Math.max(submittedTotal, expectedTotal),
        done:  valid.reduce((s, j) => s + j.done, 0),
        files: valid.flatMap(j => j.files),
      };
      setJob(merged);
      if (merged.done < submittedTotal || submittedTotal < expectedTotal) startPolling(firstId);
      else { sessionStorage.removeItem("ingest_job_id"); sessionStorage.removeItem("ingest_job_ids"); sessionStorage.removeItem("ingest_expected_total"); }
    });
  }, [startPolling]);

  useEffect(() => () => stopPoll(), [stopPoll]);

  const handleFolderSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []).filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (files.length === 0) { message.warning("所选文件夹中没有 PDF 文件"); return; }
    mergeFiles(files);
    e.target.value = "";
  };

  const mergeFiles = (files: File[]) => {
    const newItems: UploadFile[] = files.map(f => ({
      uid: `f-${f.webkitRelativePath || f.name}-${f.size}`,
      name: f.name,
      status: "done" as const,
      originFileObj: f as unknown as UploadFile["originFileObj"],
    }));
    setFileList(prev => {
      const existing = new Set(prev.map(p => p.uid));
      const added = newItems.filter(n => !existing.has(n.uid));
      if (added.length === 0) { message.info("所选文件已全部在列表中"); return prev; }
      message.success(`已添加 ${added.length} 个 PDF 文件`);
      return [...prev, ...added];
    });
  };

  const handleDropZone = (e: React.DragEvent<HTMLDivElement>) => {
    if (busy) return;
    // only intercept when folders are dropped; plain files handled by Dragger
    const items = Array.from(e.dataTransfer.items);
    const hasFolder = items.some(i => {
      const entry = i.webkitGetAsEntry?.();
      return entry?.isDirectory;
    });
    if (!hasFolder) return;
    e.preventDefault();
    e.stopPropagation();

    const readEntry = (entry: FileSystemEntry): Promise<File[]> => {
      if (entry.isFile) {
        return new Promise(resolve => {
          (entry as FileSystemFileEntry).file(
            f => resolve(f.name.toLowerCase().endsWith(".pdf") ? [f] : []),
            () => resolve([]),
          );
        });
      }
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      const readAll = (): Promise<FileSystemEntry[]> =>
        new Promise(resolve => {
          const results: FileSystemEntry[] = [];
          const read = () => reader.readEntries(batch => {
            if (batch.length === 0) { resolve(results); return; }
            results.push(...batch);
            read();
          }, () => resolve(results));
          read();
        });
      return readAll().then(entries => Promise.all(entries.map(readEntry)).then(r => r.flat()));
    };

    Promise.all(
      items.map(i => {
        const entry = i.webkitGetAsEntry?.();
        return entry ? readEntry(entry) : Promise.resolve<File[]>([]);
      })
    ).then(results => {
      const files = results.flat();
      if (files.length === 0) { message.warning("所选内容中没有 PDF 文件"); return; }
      mergeFiles(files);
    });
  };

  const BATCH_SIZE = 10;

  const handleUpload = async () => {
    if (fileList.length === 0) { message.warning("请先选择 PDF 文件"); return; }

    setUploading(true);
    uploadingRef.current = true;
    setUploadedCount(0);

    const allFiles = fileList.filter(f => f.originFileObj);
    sessionStorage.setItem("ingest_expected_total", String(allFiles.length));
    const batches: UploadFile[][] = [];
    for (let i = 0; i < allFiles.length; i += BATCH_SIZE) {
      batches.push(allFiles.slice(i, i + BATCH_SIZE));
    }

    const allJobIds: string[] = [];
    const allInitialFiles: FileRow[] = [];

    try {
      for (let i = 0; i < batches.length; i++) {
        const batch = batches[i];
        const formData = new FormData();
        batch.forEach(f => formData.append("files", f.originFileObj!));

        const res = await apiClient.post<{ job_id: string; total: number }>(
          "/api/ingest/batch", formData,
          { headers: { "Content-Type": "multipart/form-data" } },
        );
        allJobIds.push(res.data.job_id);
        batch.forEach(f => allInitialFiles.push({
          filename: f.name, status: "queued",
          category: "", target_path: "", error: "", elapsed: 0,
          poll_count: 0, max_polls: 0,
        }));

        // update sessionStorage after EACH batch so the polling loop sees new job IDs immediately
        sessionStorage.setItem("ingest_job_ids", JSON.stringify(allJobIds));
        setUploadedCount((i + 1) * BATCH_SIZE);

        if (i === 0) {
          const aggJobId = res.data.job_id;
          sessionStorage.setItem("ingest_job_id", aggJobId);
          setJob({ job_id: aggJobId, total: allFiles.length, done: 0, files: allInitialFiles });
          startPolling(aggJobId);
        }
      }
    } catch (e: unknown) {
      const err = e as { response?: { data?: { detail?: string } } };
      message.error(err?.response?.data?.detail || "上传失败，请检查服务器配置");
    } finally {
      uploadingRef.current = false;
      setUploading(false);
    }
  };

  const handleReset = () => {
    stopPoll();
    setJob(null);
    setFileList([]);
    setUploadedCount(0);
    sessionStorage.removeItem("ingest_job_id");
    sessionStorage.removeItem("ingest_job_ids");
    sessionStorage.removeItem("ingest_expected_total");
  };

  const allDone  = !!(job && job.done === job.total && job.total > 0);
  const percent  = job && job.total > 0 ? Math.round((job.done / job.total) * 100) : 0;
  const hasFail  = job?.files.some(f => f.status === "failed") ?? false;
  const busy     = uploading || (!!job && !allDone);

  const columns = [
    {
      title: "文件名",
      dataIndex: "filename",
      ellipsis: true,
      width: "28%",
      render: (v: string) => (
        <span style={{ fontSize: 13, fontWeight: 500, color: "#1e293b" }}>{v}</span>
      ),
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 150,
      render: (s: string, row: FileRow) => {
        if (s === "converting" && row.max_polls > 0) {
          const pct = Math.min(99, Math.round((row.poll_count / row.max_polls) * 100));
          return (
            <div style={{ width: 130 }}>
              <div style={{ fontSize: 11, color: "#6366f1", marginBottom: 2 }}>
                解析中 {pct}%
              </div>
              <Progress percent={pct} size="small" showInfo={false}
                strokeColor="linear-gradient(90deg,#6366f1,#7c3aed)" />
            </div>
          );
        }
        const cfg = STATUS_CFG[s] ?? { color: "default", label: s };
        return <Tag color={cfg.color}>{cfg.label}</Tag>;
      },
    },
    {
      title: "分类",
      dataIndex: "category",
      width: 120,
      render: (c: string) =>
        c ? <Tag color={categoryColor(c)}>{c}</Tag> : <span style={{ color: "#cbd5e1" }}>—</span>,
    },
    {
      title: "导入路径",
      dataIndex: "target_path",
      ellipsis: true,
      render: (p: string, row: FileRow) =>
        row.status === "failed" ? (
          <span style={{ color: "#ef4444", fontSize: 12 }}>{row.error || "失败"}</span>
        ) : (
          <span style={{ fontSize: 12, color: "#64748b" }}>{p || "—"}</span>
        ),
    },
    {
      title: "耗时",
      dataIndex: "elapsed",
      width: 72,
      render: (e: number) =>
        e > 0 ? (
          <span style={{ fontSize: 12, color: "#94a3b8" }}>{e}s</span>
        ) : (
          <span style={{ color: "#cbd5e1" }}>—</span>
        ),
    },
  ];

  return (
    <div style={{ maxWidth: 960, margin: "0 auto", padding: "32px 24px" }}>
      {/* header */}
      <div style={{ marginBottom: 24 }}>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "#1e293b", margin: 0 }}>
          批量 PDF 入库
        </h2>
        <p style={{ color: "#64748b", marginTop: 6, marginBottom: 0, fontSize: 14 }}>
          上传市场报告、竞品资料或产品文档，经转换后导入公司知识库
        </p>
      </div>

      {/* upload card */}
      <div style={{
        background: "#fff", borderRadius: 16, padding: 24,
        boxShadow: "0 1px 6px rgba(0,0,0,0.06)", marginBottom: 20,
      }}>
        <div onDrop={handleDropZone} onDragOver={e => { if (!busy) e.preventDefault(); }}>
        <Dragger
          multiple
          accept=".pdf"
          beforeUpload={() => false}
          fileList={[]}
          onChange={({ fileList: fl }) => setFileList(fl)}
          disabled={busy}
          style={{ borderRadius: 12 }}
          height={160}
        >
          <p style={{ fontSize: 40, marginBottom: 8, lineHeight: 1 }}>
            <InboxOutlined style={{ color: "#6366f1" }} />
          </p>
          <p style={{ fontSize: 15, fontWeight: 600, color: "#1e293b", marginBottom: 4 }}>
            拖拽 PDF 文件 / 文件夹到此处，或点击选择文件
          </p>
          <p style={{ fontSize: 13, color: "#94a3b8", margin: 0 }}>
            支持同时拖入多个文件夹，单文件上限 100 MB
          </p>
        </Dragger>
        </div>

        {/* file list with fixed height */}
        {fileList.length > 0 && (
          <div style={{
            marginTop: 8, maxHeight: 160, overflowY: "auto",
            border: "1px solid #f0f0f0", borderRadius: 8, padding: "4px 8px",
          }}>
            {fileList.map(f => (
              <div key={f.uid} style={{
                display: "flex", alignItems: "center", justifyContent: "space-between",
                padding: "3px 4px", fontSize: 13, color: "#374151",
              }}>
                <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                  📄 {f.name}
                </span>
                {!busy && (
                  <button
                    onClick={() => setFileList(prev => prev.filter(p => p.uid !== f.uid))}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#9ca3af", fontSize: 16, lineHeight: 1, padding: "0 4px", flexShrink: 0 }}
                  >×</button>
                )}
              </div>
            ))}
          </div>
        )}

        {/* hidden folder input */}
        <input
          ref={folderInputRef}
          type="file"
          accept=".pdf"
          // @ts-ignore — webkitdirectory is not in standard TS types
          webkitdirectory=""
          multiple
          style={{ display: "none" }}
          onChange={handleFolderSelect}
        />

        <div style={{ marginTop: 12, display: "flex", alignItems: "center", gap: 10 }}>
          <Button
            icon={<FolderOpenOutlined />}
            disabled={busy}
            onClick={() => folderInputRef.current?.click()}
            style={{ flexShrink: 0 }}
          >
            选择文件夹
          </Button>
          {fileList.length > 0 && (
            <span style={{ fontSize: 13, color: "#64748b" }}>
              已选 {fileList.length} 个文件
            </span>
          )}
        </div>

        <div style={{ marginTop: 16, display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 10 }}>
          {uploading && fileList.length > 0 && (
            <span style={{ fontSize: 13, color: "#6366f1", display: "flex", alignItems: "center", gap: 6 }}>
              正在上传 {Math.min(uploadedCount, fileList.length)} / {fileList.length} 个文件…
              <span style={{ fontSize: 12, color: "#f59e0b", background: "#fffbeb", border: "1px solid #fde68a", borderRadius: 4, padding: "1px 6px" }}>
                ⚠️ 上传期间请勿切换页面
              </span>
            </span>
          )}
          {allDone && (
            <Button icon={<ReloadOutlined />} onClick={handleReset}>
              重新导入
            </Button>
          )}
          <Button
            type="primary"
            icon={<CloudUploadOutlined />}
            loading={uploading}
            disabled={fileList.length === 0 || busy}
            onClick={handleUpload}
            style={{
              background: "linear-gradient(135deg, #6366f1 0%, #7c3aed 100%)",
              border: "none",
              borderRadius: 8,
              fontWeight: 600,
            }}
          >
            开始转换并导入{fileList.length > 0 ? `（${fileList.length} 个文件）` : ""}
          </Button>
        </div>
      </div>

      {/* progress + results */}
      {job && (
        <div style={{
          background: "#fff", borderRadius: 16, padding: 24,
          boxShadow: "0 1px 6px rgba(0,0,0,0.06)",
        }}>
          <div style={{
            display: "flex", alignItems: "center",
            justifyContent: "space-between", marginBottom: 14,
          }}>
            <span style={{ fontWeight: 600, color: "#1e293b", fontSize: 15 }}>
              转换进度
              <span style={{ fontSize: 13, fontWeight: 400, color: "#64748b", marginLeft: 8 }}>
                {job.done} / {job.total} 完成
              </span>
            </span>
            <span style={{ fontSize: 12, color: "#94a3b8" }}>任务 {job.job_id}</span>
          </div>

          <Progress
            percent={percent}
            status={allDone ? (hasFail ? "exception" : "success") : "active"}
            strokeColor={hasFail ? undefined : "linear-gradient(90deg, #6366f1, #7c3aed)"}
            style={{ marginBottom: 20 }}
          />

          {job.files.length > 0 && (
            <Table
              dataSource={job.files}
              columns={columns}
              rowKey="filename"
              size="small"
              pagination={false}
              scroll={{ y: 420 }}
              rowClassName={(row) => row.status === "failed" ? "ingest-row-failed" : ""}
            />
          )}
        </div>
      )}

      <style>{`
        .ingest-row-failed td { background: #fff5f5 !important; }
      `}</style>
    </div>
  );
}
