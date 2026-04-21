import React, { useEffect, useMemo, useState } from "react";

type ModuleId =
  | "topic_classifier"
  | "web_enrichment"
  | "template_router"
  | "embedding"
  | "rerank"
  | "llm_reasoner";

type StatusLevel = "ready" | "incomplete" | "invalid" | "connected" | "failed";

export type BaseConfig = {
  apiBaseUrl: string;
  apiKey: string;
  timeoutMs: number;
};

export type ModuleOverrideConfig = {
  enabled: boolean;
  apiUrl?: string;
  apiKey?: string;
  templatePath?: string;
  model?: string;
  extraHeaders?: Record<string, string>;
};

export type AdvancedConfig = {
  moduleOverrides: Record<ModuleId, ModuleOverrideConfig>;
  extraEnv: Array<{ key: string; value: string }>;
};

export type HarnessProfile = {
  id: string;
  name: string;
  description?: string;
  baseConfig: BaseConfig;
  advancedConfig: AdvancedConfig;
  createdAt: string;
  updatedAt: string;
  lastValidatedAt?: string;
};

export type ValidationState = {
  isValid: boolean;
  baseUrl: "valid" | "invalid" | "empty";
  apiKey: "valid" | "invalid" | "empty";
  messages: string[];
};

export type ConnectionTestState = {
  status: "idle" | "testing" | "success" | "failed";
  testedAt?: string;
  latencyMs?: number;
  error?: string;
};

export type ModuleConfigStatus = {
  moduleId: ModuleId;
  label: string;
  configured: boolean;
  source: "base" | "override" | "mixed" | "none";
  missingFields: string[];
};

type RuntimeEnvironment = {
  baseConfig: BaseConfig;
  advancedConfig: AdvancedConfig;
  updatedAt?: string;
};

type ConsoleState = {
  runtime: RuntimeEnvironment;
  profiles: HarnessProfile[];
  activeProfileId?: string;
  defaultProfileId?: string;
};

type Toast = {
  id: string;
  tone: "success" | "error" | "info";
  text: string;
};

const STORAGE_KEY = "kh_api_harness_console_v1";

const MODULE_META: Array<{ id: ModuleId; label: string; required: Array<keyof ModuleOverrideConfig | "apiBaseUrl" | "apiKey"> }> = [
  { id: "topic_classifier", label: "Topic Classifier", required: ["apiBaseUrl", "apiKey"] },
  { id: "web_enrichment", label: "Web Enrichment", required: ["apiBaseUrl", "apiKey"] },
  { id: "template_router", label: "Template Router", required: ["apiBaseUrl", "apiKey", "templatePath"] },
  { id: "embedding", label: "Embedding", required: ["apiBaseUrl", "apiKey", "model"] },
  { id: "rerank", label: "Rerank", required: ["apiBaseUrl", "apiKey", "model"] },
  { id: "llm_reasoner", label: "LLM Reasoner", required: ["apiBaseUrl", "apiKey", "model"] },
];

function emptyBaseConfig(): BaseConfig {
  return { apiBaseUrl: "", apiKey: "", timeoutMs: 8000 };
}

function emptyAdvancedConfig(): AdvancedConfig {
  return {
    moduleOverrides: {
      topic_classifier: { enabled: true },
      web_enrichment: { enabled: true },
      template_router: { enabled: false },
      embedding: { enabled: false },
      rerank: { enabled: false },
      llm_reasoner: { enabled: false },
    },
    extraEnv: [],
  };
}

function emptyConsoleState(): ConsoleState {
  return {
    runtime: { baseConfig: emptyBaseConfig(), advancedConfig: emptyAdvancedConfig() },
    profiles: [],
  };
}

function nowIso(): string {
  return new Date().toISOString();
}

function validateBaseConfig(base: BaseConfig): ValidationState {
  const messages: string[] = [];
  let baseUrl: ValidationState["baseUrl"] = "valid";
  let apiKey: ValidationState["apiKey"] = "valid";

  const url = base.apiBaseUrl.trim();
  if (!url) {
    baseUrl = "empty";
    messages.push("Base URL 未填写。");
  } else {
    try {
      const u = new URL(url);
      if (!["http:", "https:"].includes(u.protocol)) {
        baseUrl = "invalid";
        messages.push("Base URL 协议必须是 http/https。");
      }
    } catch {
      baseUrl = "invalid";
      messages.push("Base URL 格式非法。");
    }
  }

  const key = base.apiKey.trim();
  if (!key) {
    apiKey = "empty";
    messages.push("API Key 未填写。");
  } else if (key.length < 8) {
    apiKey = "invalid";
    messages.push("API Key 长度过短（至少 8 位）。");
  }

  if (base.timeoutMs < 1000 || base.timeoutMs > 120000) {
    messages.push("超时时间建议在 1000ms 到 120000ms 之间。");
  }

  return { isValid: baseUrl === "valid" && apiKey === "valid", baseUrl, apiKey, messages };
}

function getModuleStatuses(base: BaseConfig, advanced: AdvancedConfig): ModuleConfigStatus[] {
  return MODULE_META.map((m) => {
    const ov = advanced.moduleOverrides[m.id] ?? { enabled: false };
    if (!ov.enabled) {
      return { moduleId: m.id, label: m.label, configured: true, source: "none", missingFields: [] };
    }

    const missing: string[] = [];
    const fromOverride = Boolean(ov.apiUrl?.trim()) || Boolean(ov.apiKey?.trim()) || Boolean(ov.model?.trim()) || Boolean(ov.templatePath?.trim());
    for (const req of m.required) {
      if (req === "apiBaseUrl") {
        const ok = Boolean((ov.apiUrl || base.apiBaseUrl).trim());
        if (!ok) missing.push("apiBaseUrl");
      } else if (req === "apiKey") {
        const ok = Boolean((ov.apiKey || base.apiKey).trim());
        if (!ok) missing.push("apiKey");
      } else if (!String(ov[req] || "").trim()) {
        missing.push(String(req));
      }
    }

    let source: ModuleConfigStatus["source"] = "base";
    if (fromOverride && (base.apiBaseUrl.trim() || base.apiKey.trim())) source = "mixed";
    else if (fromOverride) source = "override";
    else if (!base.apiBaseUrl.trim() && !base.apiKey.trim()) source = "none";

    return {
      moduleId: m.id,
      label: m.label,
      configured: missing.length === 0,
      source,
      missingFields: missing,
    };
  });
}

function statusLabel(level: StatusLevel): string {
  if (level === "ready") return "Ready";
  if (level === "connected") return "Connected";
  if (level === "failed") return "Failed";
  if (level === "invalid") return "Invalid";
  return "Incomplete";
}

function statusTone(level: StatusLevel): string {
  if (level === "ready" || level === "connected") return "bg-emerald-100 text-emerald-700 border-emerald-300";
  if (level === "failed" || level === "invalid") return "bg-rose-100 text-rose-700 border-rose-300";
  return "bg-amber-100 text-amber-700 border-amber-300";
}

function deepClone<T>(obj: T): T {
  return JSON.parse(JSON.stringify(obj)) as T;
}

function uid(prefix: string): string {
  return `${prefix}_${Math.random().toString(36).slice(2, 10)}`;
}

function ConfigStatusBadge({ level, text }: { level: StatusLevel; text?: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-medium ${statusTone(level)}`}>
      {text ?? statusLabel(level)}
    </span>
  );
}

function TestConnectionButton({
  disabled,
  state,
  onRun,
}: {
  disabled?: boolean;
  state: ConnectionTestState;
  onRun: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled || state.status === "testing"}
      onClick={onRun}
      className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
    >
      {state.status === "testing" ? "连接测试中..." : "测试连接"}
    </button>
  );
}

function HarnessStatusOverview(props: {
  runtime: RuntimeEnvironment;
  activeProfile?: HarnessProfile;
  defaultProfile?: HarnessProfile;
  validation: ValidationState;
  testState: ConnectionTestState;
  moduleStatuses: ModuleConfigStatus[];
}) {
  const configuredCount = props.moduleStatuses.filter((x) => x.configured).length;
  const total = props.moduleStatuses.length;
  const level: StatusLevel = !props.validation.isValid
    ? "invalid"
    : props.testState.status === "success"
      ? "connected"
      : props.testState.status === "failed"
        ? "failed"
        : configuredCount === total
          ? "ready"
          : "incomplete";

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-slate-900">运行状态总览</h2>
          <p className="mt-1 text-sm text-slate-500">先看状态，再做配置操作。当前页遵循 Harness 生命周期：状态 → 配置 → 应用 → 治理。</p>
        </div>
        <ConfigStatusBadge level={level} />
      </div>
      <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-5">
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">当前激活档案</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{props.activeProfile?.name || "未指定"}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">默认档案</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{props.defaultProfile?.name || "未指定"}</div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">模块完成度</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {configuredCount}/{total}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">最近连接测试</div>
          <div className="mt-1 text-sm font-medium text-slate-900">
            {props.testState.status === "success"
              ? `成功 (${props.testState.latencyMs ?? "-"}ms)`
              : props.testState.status === "failed"
                ? "失败"
                : "未测试"}
          </div>
        </div>
        <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs text-slate-500">运行环境更新时间</div>
          <div className="mt-1 text-sm font-medium text-slate-900">{props.runtime.updatedAt ? new Date(props.runtime.updatedAt).toLocaleString() : "未保存"}</div>
        </div>
      </div>
    </section>
  );
}

function BaseConfigPanel(props: {
  value: BaseConfig;
  validation: ValidationState;
  keyVisible: boolean;
  onChange: (next: BaseConfig) => void;
  onToggleKeyVisible: () => void;
  onCopyKey: () => void;
  onSaveCurrent: () => void;
  testState: ConnectionTestState;
  onTest: () => void;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">基础配置（主任务区）</h3>
        <div className="flex items-center gap-2">
          <TestConnectionButton state={props.testState} onRun={props.onTest} />
          <button
            type="button"
            onClick={props.onSaveCurrent}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white hover:bg-black"
          >
            保存当前配置
          </button>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-slate-600">Base URL</label>
          <input
            value={props.value.apiBaseUrl}
            onChange={(e) => props.onChange({ ...props.value, apiBaseUrl: e.target.value })}
            placeholder="https://api.example.com/v1"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          />
          <p className="mt-1 text-xs text-slate-500">必须是 http/https；建议填写网关基础地址。</p>
        </div>
        <div>
          <label className="block text-xs font-medium text-slate-600">API Key</label>
          <div className="mt-1 flex gap-2">
            <input
              type={props.keyVisible ? "text" : "password"}
              value={props.value.apiKey}
              onChange={(e) => props.onChange({ ...props.value, apiKey: e.target.value })}
              placeholder="输入访问密钥"
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
            />
            <button type="button" onClick={props.onToggleKeyVisible} className="rounded-md border border-slate-300 px-3 py-2 text-xs text-slate-700">
              {props.keyVisible ? "隐藏" : "显示"}
            </button>
            <button type="button" onClick={props.onCopyKey} className="rounded-md border border-slate-300 px-3 py-2 text-xs text-slate-700">
              复制
            </button>
          </div>
          <p className="mt-1 text-xs text-slate-500">密钥仅用于当前浏览器会话与本地存储。</p>
        </div>
      </div>
      <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
        <div>
          <label className="block text-xs font-medium text-slate-600">请求超时（ms）</label>
          <input
            type="number"
            value={props.value.timeoutMs}
            onChange={(e) => props.onChange({ ...props.value, timeoutMs: Number(e.target.value || 0) })}
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          />
        </div>
        <div className="rounded-md border border-slate-200 bg-slate-50 p-3">
          <div className="text-xs font-medium text-slate-600">输入校验</div>
          <ul className="mt-2 space-y-1 text-xs text-slate-700">
            <li>Base URL: {props.validation.baseUrl}</li>
            <li>API Key: {props.validation.apiKey}</li>
            {props.validation.messages.length === 0 ? <li>校验通过。</li> : props.validation.messages.map((m) => <li key={m}>- {m}</li>)}
          </ul>
        </div>
      </div>
    </section>
  );
}

function AdvancedConfigAccordion(props: {
  value: AdvancedConfig;
  moduleStatuses: ModuleConfigStatus[];
  onChange: (next: AdvancedConfig) => void;
}) {
  const updateModule = (moduleId: ModuleId, patch: Partial<ModuleOverrideConfig>) => {
    props.onChange({
      ...props.value,
      moduleOverrides: {
        ...props.value.moduleOverrides,
        [moduleId]: { ...props.value.moduleOverrides[moduleId], ...patch },
      },
    });
  };

  const addEnv = () => props.onChange({ ...props.value, extraEnv: [...props.value.extraEnv, { key: "", value: "" }] });
  const removeEnv = (idx: number) => props.onChange({ ...props.value, extraEnv: props.value.extraEnv.filter((_, i) => i !== idx) });
  const updateEnv = (idx: number, patch: { key?: string; value?: string }) => {
    props.onChange({
      ...props.value,
      extraEnv: props.value.extraEnv.map((item, i) => (i === idx ? { ...item, ...patch } : item)),
    });
  };

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <details open className="group">
        <summary className="cursor-pointer list-none text-sm font-semibold text-slate-900">
          高级配置（Advanced Configuration）
          <span className="ml-2 text-xs text-slate-500">模块扩展、模板、额外环境变量</span>
        </summary>
        <div className="mt-4 space-y-4">
          {MODULE_META.map((m) => {
            const ov = props.value.moduleOverrides[m.id];
            const st = props.moduleStatuses.find((x) => x.moduleId === m.id)!;
            return (
              <details key={m.id} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                <summary className="cursor-pointer text-sm font-medium text-slate-800">
                  {m.label}
                  <span className="ml-2 text-xs text-slate-500">({st.configured ? "configured" : `missing: ${st.missingFields.join(", ")}`})</span>
                </summary>
                <div className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
                  <label className="text-xs text-slate-600">
                    <input
                      type="checkbox"
                      checked={ov.enabled}
                      onChange={(e) => updateModule(m.id, { enabled: e.target.checked })}
                      className="mr-2"
                    />
                    启用模块
                  </label>
                  <div />
                  <div>
                    <div className="text-xs font-medium text-slate-600">模块 API URL 覆盖</div>
                    <input
                      value={ov.apiUrl || ""}
                      onChange={(e) => updateModule(m.id, { apiUrl: e.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      placeholder="为空则回退统一 Base URL"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-600">模块 API Key 覆盖</div>
                    <input
                      value={ov.apiKey || ""}
                      onChange={(e) => updateModule(m.id, { apiKey: e.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      placeholder="为空则回退统一 API Key"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-600">模板路径</div>
                    <input
                      value={ov.templatePath || ""}
                      onChange={(e) => updateModule(m.id, { templatePath: e.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      placeholder="可选"
                    />
                  </div>
                  <div>
                    <div className="text-xs font-medium text-slate-600">模型</div>
                    <input
                      value={ov.model || ""}
                      onChange={(e) => updateModule(m.id, { model: e.target.value })}
                      className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                      placeholder="可选"
                    />
                  </div>
                </div>
              </details>
            );
          })}

          <div className="rounded-lg border border-slate-200 bg-white p-3">
            <div className="flex items-center justify-between">
              <div className="text-sm font-medium text-slate-800">额外环境变量</div>
              <button type="button" onClick={addEnv} className="rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700">
                新增变量
              </button>
            </div>
            <div className="mt-3 space-y-2">
              {props.value.extraEnv.length === 0 ? (
                <p className="text-xs text-slate-500">暂无额外变量。</p>
              ) : (
                props.value.extraEnv.map((it, idx) => (
                  <div key={`env-${idx}`} className="grid grid-cols-1 gap-2 md:grid-cols-[1fr_1fr_auto]">
                    <input
                      value={it.key}
                      onChange={(e) => updateEnv(idx, { key: e.target.value })}
                      placeholder="KEY"
                      className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                    />
                    <input
                      value={it.value}
                      onChange={(e) => updateEnv(idx, { value: e.target.value })}
                      placeholder="VALUE"
                      className="rounded-md border border-slate-300 px-3 py-2 text-sm"
                    />
                    <button type="button" onClick={() => removeEnv(idx)} className="rounded-md border border-rose-300 px-3 py-2 text-xs text-rose-700">
                      删除
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>
        </div>
      </details>
    </section>
  );
}

function ProfileListPanel(props: {
  profiles: HarnessProfile[];
  selectedId?: string;
  activeId?: string;
  defaultId?: string;
  onSelect: (id: string) => void;
  onCreate: (name: string, desc: string) => void;
  onApply: (id: string, setDefault: boolean) => void;
  onSetDefault: (id: string) => void;
}) {
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <h3 className="text-sm font-semibold text-slate-900">Harness Profiles</h3>
      <p className="mt-1 text-xs text-slate-500">Profile 是核心对象：可切换、可追踪、可复用。</p>
      <div className="mt-3 rounded-md border border-slate-200 p-3">
        <div className="grid grid-cols-1 gap-2">
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder="新档案名称" className="rounded-md border border-slate-300 px-3 py-2 text-sm" />
          <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="描述（可选）" className="rounded-md border border-slate-300 px-3 py-2 text-sm" />
          <button
            type="button"
            onClick={() => {
              props.onCreate(name, desc);
              setName("");
              setDesc("");
            }}
            className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white"
          >
            保存当前配置为档案
          </button>
        </div>
      </div>
      <div className="mt-3 space-y-2">
        {props.profiles.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-300 p-3 text-xs text-slate-500">暂无档案。先保存一个档案，再进行应用/默认切换。</div>
        ) : (
          props.profiles.map((p) => (
            <div
              key={p.id}
              className={`rounded-md border p-3 ${props.selectedId === p.id ? "border-slate-900 bg-slate-50" : "border-slate-200 bg-white"}`}
            >
              <div className="flex items-start justify-between gap-2">
                <button type="button" onClick={() => props.onSelect(p.id)} className="text-left">
                  <div className="text-sm font-medium text-slate-900">{p.name}</div>
                  <div className="mt-1 text-xs text-slate-500">{p.description || "无描述"}</div>
                </button>
                <div className="flex flex-wrap gap-1">
                  {props.activeId === p.id ? <ConfigStatusBadge level="connected" text="Active" /> : null}
                  {props.defaultId === p.id ? <ConfigStatusBadge level="ready" text="Default" /> : null}
                </div>
              </div>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" onClick={() => props.onApply(p.id, false)} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700">
                  应用
                </button>
                <button type="button" onClick={() => props.onApply(p.id, true)} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700">
                  应用并设默认
                </button>
                <button type="button" onClick={() => props.onSetDefault(p.id)} className="rounded border border-slate-300 px-2 py-1 text-xs text-slate-700">
                  仅设默认
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </section>
  );
}

function ProfileDetailPanel(props: {
  profile?: HarnessProfile;
  draft: RuntimeEnvironment;
  onOverwriteFromCurrent: () => void;
}) {
  const diffRows = useMemo(() => {
    if (!props.profile) return [];
    const rows: Array<{ field: string; current: string; profile: string }> = [];
    const push = (field: string, current: string, profile: string) => {
      if ((current || "") !== (profile || "")) rows.push({ field, current, profile });
    };
    push("apiBaseUrl", props.draft.baseConfig.apiBaseUrl, props.profile.baseConfig.apiBaseUrl);
    push("apiKey", props.draft.baseConfig.apiKey ? "******" : "", props.profile.baseConfig.apiKey ? "******" : "");
    push("timeoutMs", String(props.draft.baseConfig.timeoutMs), String(props.profile.baseConfig.timeoutMs));
    MODULE_META.forEach((m) => {
      const d = props.draft.advancedConfig.moduleOverrides[m.id];
      const p = props.profile!.advancedConfig.moduleOverrides[m.id];
      push(`${m.id}.enabled`, String(d.enabled), String(p.enabled));
      push(`${m.id}.apiUrl`, d.apiUrl || "", p.apiUrl || "");
      push(`${m.id}.model`, d.model || "", p.model || "");
      push(`${m.id}.templatePath`, d.templatePath || "", p.templatePath || "");
    });
    return rows;
  }, [props.profile, props.draft]);

  if (!props.profile) {
    return (
      <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
        <h3 className="text-sm font-semibold text-slate-900">Profile 详情</h3>
        <p className="mt-2 text-xs text-slate-500">请先在左侧选择一个 Profile。</p>
      </section>
    );
  }

  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-slate-900">{props.profile.name}</h3>
          <p className="mt-1 text-xs text-slate-500">{props.profile.description || "无描述"} · 更新于 {new Date(props.profile.updatedAt).toLocaleString()}</p>
        </div>
        <button type="button" onClick={props.onOverwriteFromCurrent} className="rounded-md border border-amber-400 bg-amber-50 px-3 py-2 text-xs font-medium text-amber-700">
          用当前环境覆盖此档案
        </button>
      </div>
      <div className="mt-3 rounded-md border border-slate-200 p-3">
        <div className="text-xs font-medium text-slate-600">字段状态</div>
        <div className="mt-2 grid grid-cols-1 gap-2 md:grid-cols-2">
          <div className="rounded bg-slate-50 p-2 text-xs text-slate-700">Base URL: {props.profile.baseConfig.apiBaseUrl || "未配置"}</div>
          <div className="rounded bg-slate-50 p-2 text-xs text-slate-700">API Key: {props.profile.baseConfig.apiKey ? "已配置（掩码）" : "未配置"}</div>
        </div>
      </div>
      <div className="mt-3 rounded-md border border-slate-200 p-3">
        <div className="text-xs font-medium text-slate-600">与当前环境差异</div>
        {diffRows.length === 0 ? (
          <p className="mt-2 text-xs text-emerald-700">当前环境与该档案一致。</p>
        ) : (
          <ul className="mt-2 max-h-52 space-y-1 overflow-auto text-xs text-slate-700">
            {diffRows.map((r) => (
              <li key={r.field}>
                {r.field}: current="{r.current || "∅"}" vs profile="{r.profile || "∅"}"
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}

function DangerZonePanel(props: {
  hasSelection: boolean;
  onDeleteSelected: () => void;
  onClearRuntime: () => void;
}) {
  return (
    <section className="rounded-xl border border-rose-200 bg-rose-50 p-4 shadow-sm">
      <details>
        <summary className="cursor-pointer text-sm font-semibold text-rose-700">危险操作区（需二次确认）</summary>
        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={!props.hasSelection}
            onClick={props.onDeleteSelected}
            className="rounded-md border border-rose-300 px-3 py-2 text-xs font-medium text-rose-700 disabled:cursor-not-allowed disabled:opacity-50"
          >
            删除选中档案
          </button>
          <button type="button" onClick={props.onClearRuntime} className="rounded-md border border-rose-300 px-3 py-2 text-xs font-medium text-rose-700">
            清空当前环境配置
          </button>
        </div>
      </details>
    </section>
  );
}

function ToastStack({ toasts, onClose }: { toasts: Toast[]; onClose: (id: string) => void }) {
  return (
    <div className="fixed right-4 top-4 z-50 space-y-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`min-w-[260px] rounded-md border px-3 py-2 text-sm shadow ${
            t.tone === "success"
              ? "border-emerald-300 bg-emerald-50 text-emerald-700"
              : t.tone === "error"
                ? "border-rose-300 bg-rose-50 text-rose-700"
                : "border-slate-300 bg-white text-slate-700"
          }`}
        >
          <div className="flex items-start justify-between gap-3">
            <span>{t.text}</span>
            <button type="button" onClick={() => onClose(t.id)} className="text-xs opacity-70 hover:opacity-100">
              关闭
            </button>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ApiHarnessSettingsPage() {
  const [state, setState] = useState<ConsoleState>(emptyConsoleState());
  const [draft, setDraft] = useState<RuntimeEnvironment>(deepClone(emptyConsoleState().runtime));
  const [selectedProfileId, setSelectedProfileId] = useState<string | undefined>();
  const [keyVisible, setKeyVisible] = useState(false);
  const [testState, setTestState] = useState<ConnectionTestState>({ status: "idle" });
  const [toasts, setToasts] = useState<Toast[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as ConsoleState;
        if (parsed.runtime && parsed.profiles) {
          setState(parsed);
          setDraft(deepClone(parsed.runtime));
          setSelectedProfileId(parsed.activeProfileId);
        }
      }
    } catch {
      // ignore bad local state
    }
  }, []);

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  }, [state]);

  const validation = useMemo(() => validateBaseConfig(draft.baseConfig), [draft.baseConfig]);
  const moduleStatuses = useMemo(
    () => getModuleStatuses(draft.baseConfig, draft.advancedConfig),
    [draft.baseConfig, draft.advancedConfig]
  );
  const selectedProfile = state.profiles.find((p) => p.id === selectedProfileId);
  const activeProfile = state.profiles.find((p) => p.id === state.activeProfileId);
  const defaultProfile = state.profiles.find((p) => p.id === state.defaultProfileId);

  const notify = (tone: Toast["tone"], text: string) => {
    const id = uid("toast");
    setToasts((prev) => [...prev, { id, tone, text }]);
    window.setTimeout(() => setToasts((prev) => prev.filter((x) => x.id !== id)), 3500);
  };

  const saveCurrentConfig = () => {
    if (!validation.isValid) {
      notify("error", "基础配置校验未通过，不能保存到运行环境。");
      return;
    }
    setState((prev) => ({
      ...prev,
      runtime: deepClone({ ...draft, updatedAt: nowIso() }),
    }));
    notify("success", "已保存当前配置到运行环境。");
  };

  const runConnectionTest = async () => {
    const check = validateBaseConfig(draft.baseConfig);
    if (!check.isValid) {
      setTestState({ status: "failed", testedAt: nowIso(), error: check.messages.join(" ") || "校验失败" });
      notify("error", "连接测试前请先修复基础配置。");
      return;
    }

    setTestState({ status: "testing" });
    const begin = performance.now();
    try {
      const target = draft.baseConfig.apiBaseUrl.replace(/\/+$/, "") + "/health";
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), Math.max(1000, draft.baseConfig.timeoutMs));
      const res = await fetch(target, {
        method: "GET",
        headers: {
          Authorization: `Bearer ${draft.baseConfig.apiKey}`,
        },
        signal: controller.signal,
      });
      window.clearTimeout(timeout);
      const latency = Math.round(performance.now() - begin);
      if (!res.ok) {
        setTestState({ status: "failed", testedAt: nowIso(), latencyMs: latency, error: `HTTP ${res.status}` });
        notify("error", `连接失败：HTTP ${res.status}`);
        return;
      }
      setTestState({ status: "success", testedAt: nowIso(), latencyMs: latency });
      notify("success", `连接成功（${latency}ms）`);
    } catch (err: any) {
      const latency = Math.round(performance.now() - begin);
      setTestState({ status: "failed", testedAt: nowIso(), latencyMs: latency, error: err?.message || "网络错误" });
      notify("error", `连接失败：${err?.message || "网络错误"}`);
    }
  };

  const createProfileFromDraft = (name: string, desc: string) => {
    const n = name.trim();
    if (!n) {
      notify("error", "请输入档案名称。");
      return;
    }
    setState((prev) => {
      const exists = prev.profiles.find((p) => p.name === n);
      if (exists) {
        const next = {
          ...exists,
          description: desc.trim(),
          baseConfig: deepClone(draft.baseConfig),
          advancedConfig: deepClone(draft.advancedConfig),
          updatedAt: nowIso(),
        };
        return { ...prev, profiles: prev.profiles.map((p) => (p.id === exists.id ? next : p)) };
      }
      const profile: HarnessProfile = {
        id: uid("profile"),
        name: n,
        description: desc.trim(),
        baseConfig: deepClone(draft.baseConfig),
        advancedConfig: deepClone(draft.advancedConfig),
        createdAt: nowIso(),
        updatedAt: nowIso(),
      };
      return { ...prev, profiles: [profile, ...prev.profiles] };
    });
    notify("success", "档案已保存。");
  };

  const applyProfile = (id: string, setDefault: boolean) => {
    const p = state.profiles.find((x) => x.id === id);
    if (!p) return;
    setDraft({ baseConfig: deepClone(p.baseConfig), advancedConfig: deepClone(p.advancedConfig), updatedAt: nowIso() });
    setState((prev) => ({
      ...prev,
      runtime: { baseConfig: deepClone(p.baseConfig), advancedConfig: deepClone(p.advancedConfig), updatedAt: nowIso() },
      activeProfileId: id,
      defaultProfileId: setDefault ? id : prev.defaultProfileId,
    }));
    setSelectedProfileId(id);
    notify("success", setDefault ? `已应用并设为默认：${p.name}` : `已应用：${p.name}`);
  };

  const setDefaultProfile = (id: string) => {
    const p = state.profiles.find((x) => x.id === id);
    if (!p) return;
    setState((prev) => ({ ...prev, defaultProfileId: id }));
    notify("info", `默认档案已切换为：${p.name}`);
  };

  const overwriteSelectedProfileFromCurrent = () => {
    if (!selectedProfileId) return;
    const p = state.profiles.find((x) => x.id === selectedProfileId);
    if (!p) return;
    const ok = window.confirm(`确认用当前环境覆盖档案 "${p.name}"？此操作不可撤销。`);
    if (!ok) return;
    setState((prev) => ({
      ...prev,
      profiles: prev.profiles.map((x) =>
        x.id === selectedProfileId
          ? { ...x, baseConfig: deepClone(draft.baseConfig), advancedConfig: deepClone(draft.advancedConfig), updatedAt: nowIso() }
          : x
      ),
    }));
    notify("success", `已覆盖档案：${p.name}`);
  };

  const deleteSelectedProfile = () => {
    if (!selectedProfileId) return;
    const p = state.profiles.find((x) => x.id === selectedProfileId);
    if (!p) return;
    const ok = window.confirm(`确认删除档案 "${p.name}"？此操作不可撤销。`);
    if (!ok) return;
    setState((prev) => ({
      ...prev,
      profiles: prev.profiles.filter((x) => x.id !== selectedProfileId),
      activeProfileId: prev.activeProfileId === selectedProfileId ? undefined : prev.activeProfileId,
      defaultProfileId: prev.defaultProfileId === selectedProfileId ? undefined : prev.defaultProfileId,
    }));
    setSelectedProfileId(undefined);
    notify("info", `已删除档案：${p.name}`);
  };

  const clearRuntime = () => {
    const ok = window.confirm("确认清空当前环境配置？该操作不会删除档案。");
    if (!ok) return;
    const clean = { baseConfig: emptyBaseConfig(), advancedConfig: emptyAdvancedConfig(), updatedAt: nowIso() };
    setDraft(deepClone(clean));
    setState((prev) => ({ ...prev, runtime: deepClone(clean), activeProfileId: undefined }));
    setTestState({ status: "idle" });
    notify("info", "当前环境配置已清空。");
  };

  const copyApiKey = async () => {
    try {
      await navigator.clipboard.writeText(draft.baseConfig.apiKey || "");
      notify("success", "API Key 已复制到剪贴板。");
    } catch {
      notify("error", "复制失败，请检查浏览器权限。");
    }
  };

  return (
    <div className="min-h-screen bg-slate-100 p-4 md:p-6">
      <ToastStack toasts={toasts} onClose={(id) => setToasts((prev) => prev.filter((x) => x.id !== id))} />

      <div className="mx-auto max-w-7xl space-y-4">
        <header className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          <h1 className="text-lg font-semibold text-slate-900">API Harness 配置控制台</h1>
          <p className="mt-1 text-sm text-slate-500">配置即资产：可验证、可保存、可应用、可治理。</p>
        </header>

        <HarnessStatusOverview
          runtime={state.runtime}
          activeProfile={activeProfile}
          defaultProfile={defaultProfile}
          validation={validation}
          testState={testState}
          moduleStatuses={moduleStatuses}
        />

        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1.25fr_1fr]">
          <div className="space-y-4">
            <BaseConfigPanel
              value={draft.baseConfig}
              validation={validation}
              keyVisible={keyVisible}
              onChange={(next) => setDraft((prev) => ({ ...prev, baseConfig: next }))}
              onToggleKeyVisible={() => setKeyVisible((v) => !v)}
              onCopyKey={copyApiKey}
              onSaveCurrent={saveCurrentConfig}
              testState={testState}
              onTest={runConnectionTest}
            />
            <AdvancedConfigAccordion
              value={draft.advancedConfig}
              moduleStatuses={moduleStatuses}
              onChange={(next) => setDraft((prev) => ({ ...prev, advancedConfig: next }))}
            />
            <DangerZonePanel hasSelection={Boolean(selectedProfileId)} onDeleteSelected={deleteSelectedProfile} onClearRuntime={clearRuntime} />
          </div>

          <div className="space-y-4">
            <ProfileListPanel
              profiles={state.profiles}
              selectedId={selectedProfileId}
              activeId={state.activeProfileId}
              defaultId={state.defaultProfileId}
              onSelect={setSelectedProfileId}
              onCreate={createProfileFromDraft}
              onApply={applyProfile}
              onSetDefault={setDefaultProfile}
            />
            <ProfileDetailPanel profile={selectedProfile} draft={draft} onOverwriteFromCurrent={overwriteSelectedProfileFromCurrent} />
          </div>
        </div>
      </div>
    </div>
  );
}

