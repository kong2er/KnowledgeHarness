# Harness API 配置控制台重构说明

## 1) 工程化重构思路

- 这不是“排版问题”，而是“对象模型问题”：原页面把输入、验证、应用、治理混成一个表单流，导致高误触和低可维护。
- 新核心对象：
  - `RuntimeEnvironment`：当前运行环境配置（真实生效对象）
  - `HarnessProfile`：可复用配置资产（可保存、切换、追踪）
  - `ModuleConfigStatus`：模块级配置完成度（扩展锚点）
  - `ValidationState` + `ConnectionTestState`：配置正确性与连通性反馈
- 新主流程：
  - 状态总览 -> 基础配置 -> 连接测试 -> 保存配置 -> Profile 管理/应用 -> 危险治理
- 扩展性收益：
  - 新模块只需追加 `ModuleId` 与 `MODULE_META`，无需重写页面结构。

## 2) 新信息架构

- 顶部：`HarnessStatusOverview`
  - 当前激活档案、默认档案、模块完成度、最近测试、环境更新时间、Ready/Invalid/Failed 等状态
- 主区左列：
  - `BaseConfigPanel`（默认展开）
  - `AdvancedConfigAccordion`（默认折叠但可展开）
  - `DangerZonePanel`（折叠 + 二次确认）
- 右列：
  - `ProfileListPanel`（列表 + 新建 + 应用）
  - `ProfileDetailPanel`（单一详情逻辑 + 差异视图）

## 3) 关键交互与状态系统

- URL/API Key 输入校验：`validateBaseConfig`
- API Key 显隐/复制：基础配置区按钮
- 测试连接：`TestConnectionButton` + `ConnectionTestState`
- 保存/应用反馈：Toast 反馈
- 默认档案切换：独立操作（仅设默认）
- 危险操作：`window.confirm` 二次确认（删除、覆盖、清空）
- 空状态：无档案时显示引导文案
- 模块完成度：`ModuleConfigStatus[]` 直接展示已配置/缺失字段

## 4) 数据模型

- 类型在实现文件中完整定义：
  - `BaseConfig`
  - `AdvancedConfig`
  - `HarnessProfile`
  - `ValidationState`
  - `ConnectionTestState`
  - `ModuleConfigStatus`

## 5) 组件架构

- `ApiHarnessSettingsPage`：页面编排与状态容器
- `HarnessStatusOverview`：状态总览
- `BaseConfigPanel`：基础配置 + 测试 + 保存
- `AdvancedConfigAccordion`：模块化高级配置
- `ProfileListPanel`：档案列表与创建/应用
- `ProfileDetailPanel`：详情与差异
- `DangerZonePanel`：危险治理
- `TestConnectionButton`、`ConfigStatusBadge`、`ToastStack`：通用交互组件

## 6) 完整实现文件

- `frontend/harness-console/ApiHarnessSettingsPage.tsx`

> 该文件是单文件可运行版 React + TypeScript + Tailwind 页面，可直接放入现有 React 工程路由中挂载。

