'use client';

/**
 * FlowDiagram — 用 React Flow + dagre 自动布局渲染 10 节点 DAG。
 *
 * 节点状态颜色：
 *   done       → 蓝（已完成）
 *   waiting_human → 黄（当前处理中，闪烁高亮）
 *   rejected   → 红
 *   returned   → 橙
 *   未开始     → 灰虚线
 *
 * 节点点击 → 跳到对应处理页（节点处理页含 advance/return/reject + 邮件催办）。
 */

import { useMemo, useCallback } from 'react';
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeProps,
  Handle,
  Position,
} from '@xyflow/react';
import * as dagre from 'dagre';
import '@xyflow/react/dist/style.css';
import { useRouter } from 'next/navigation';
import type { NodeDetail } from '@/lib/api';

interface FlowDiagramProps {
  flowId: string;
  nodes: NodeDetail[];
}

// 固定 11 节点 DAG（含 fan-out 5 并行）
const NODE_DEFS: Array<{ short: string; name: string; label: string }> = [
  { short: 'apply', name: 'apply', label: '离职申请' },
  { short: 'mgr', name: 'manager_review', label: '上级审批' },
  { short: 'hr1', name: 'hr_initial', label: 'HR 初审' },
  { short: 'dev', name: 'device_return', label: '设备归还' },
  { short: 'acc', name: 'access_revoke', label: '权限回收' },
  { short: 'kh', name: 'knowledge_handover', label: '知识交接' },
  { short: 'fin', name: 'finance_settle', label: '财务结算' },
  { short: 'lgl', name: 'legal_sign', label: '法务签字' },
  { short: 'hrf', name: 'hr_final', label: 'HR 终审' },
  { short: 'afc', name: 'applicant_final_confirm', label: '申请人确认' },
  { short: 'arc', name: 'auto_archive_to_storage', label: '归档' },
];

const EDGES: Array<[string, string]> = [
  ['apply', 'mgr'],
  ['mgr', 'hr1'],
  ['hr1', 'dev'],
  ['hr1', 'acc'],
  ['hr1', 'kh'],
  ['hr1', 'fin'],
  ['hr1', 'lgl'],
  ['dev', 'hrf'],
  ['acc', 'hrf'],
  ['kh', 'hrf'],
  ['fin', 'hrf'],
  ['lgl', 'hrf'],
  ['hrf', 'afc'],
  ['afc', 'arc'],
];

// 状态 → 样式
function styleForStatus(status: string | undefined): {
  bg: string;
  border: string;
  text: string;
  pulse: boolean;
} {
  switch (status) {
    case 'done':
      return {
        bg: '#dbeafe',
        border: '#1d4ed8',
        text: '#1e3a8a',
        pulse: false,
      };
    case 'waiting_human':
      return {
        bg: '#fef3c7',
        border: '#d97706',
        text: '#92400e',
        pulse: true,
      };
    case 'rejected':
      return {
        bg: '#fee2e2',
        border: '#dc2626',
        text: '#991b1b',
        pulse: false,
      };
    case 'returned':
      return {
        bg: '#ffedd5',
        border: '#ea580c',
        text: '#9a3412',
        pulse: false,
      };
    default:
      return {
        bg: '#f9fafb',
        border: '#9ca3af',
        text: '#6b7280',
        pulse: false,
      };
  }
}

// 自定义节点
function FlowNode({ data }: NodeProps) {
  const d = data as {
    label: string;
    assignee?: string | null;
    status?: string;
    title?: string;
    onClick?: () => void;
    clickable?: boolean;
  };
  const s = styleForStatus(d.status);

  return (
    <div
      onClick={d.clickable ? d.onClick : undefined}
      style={{
        background: s.bg,
        border: `2px solid ${s.border}`,
        borderRadius: 8,
        padding: '10px 14px',
        minWidth: 130,
        cursor: d.clickable ? 'pointer' : 'default',
        boxShadow: s.pulse
          ? `0 0 0 4px ${s.border}33, 0 4px 12px rgba(0,0,0,0.1)`
          : '0 1px 3px rgba(0,0,0,0.08)',
        transition: 'all 0.2s',
        animation: s.pulse ? 'flowdiag-pulse 1.6s ease-in-out infinite' : 'none',
      }}
    >
      <Handle type="target" position={Position.Left} style={{ background: s.border }} />
      <div style={{ color: s.text, fontWeight: 600, fontSize: 13 }}>{d.label}</div>
      {d.assignee && (
        <div
          style={{
            fontSize: 11,
            color: s.text,
            opacity: 0.75,
            marginTop: 3,
            fontFamily: 'monospace',
          }}
        >
          @{d.assignee}
        </div>
      )}
      {d.status === 'waiting_human' && d.clickable && (
        <div
          style={{
            fontSize: 10,
            color: s.text,
            marginTop: 4,
            opacity: 0.8,
          }}
        >
          ▶ 点击处理
        </div>
      )}
      <Handle type="source" position={Position.Right} style={{ background: s.border }} />
    </div>
  );
}

const nodeTypes = { flowNode: FlowNode };

// dagre 自动布局
function layout(nodes: Node[], edges: Edge[]): { nodes: Node[]; edges: Edge[] } {
  const g = new dagre.graphlib.Graph();
  g.setDefaultEdgeLabel(() => ({}));
  g.setGraph({ rankdir: 'LR', nodesep: 24, ranksep: 60, marginx: 20, marginy: 20 });

  nodes.forEach((n) => g.setNode(n.id, { width: 160, height: 70 }));
  edges.forEach((e) => g.setEdge(e.source, e.target));
  dagre.layout(g);

  return {
    nodes: nodes.map((n) => {
      const { x, y } = g.node(n.id);
      return {
        ...n,
        position: { x: x - 80, y: y - 35 },
        targetPosition: Position.Left,
        sourcePosition: Position.Right,
      };
    }),
    edges,
  };
}

export function FlowDiagram({ flowId, nodes: backendNodes }: FlowDiagramProps) {
  const router = useRouter();
  const byName = useMemo(
    () => Object.fromEntries(backendNodes.map((n) => [n.name, n])),
    [backendNodes],
  );

  const handleNodeClick = useCallback(
    (nodeName: string) => {
      const nd = byName[nodeName];
      if (!nd || nd.status !== 'waiting_human') return;
      const url =
        nodeName === 'applicant_final_confirm'
          ? `/flow/${flowId}/applicant-confirm/`
          : `/flow/${flowId}/node/${nd.id}/`;
      router.push(url);
    },
    [byName, flowId, router],
  );

  const { nodes, edges } = useMemo(() => {
    const rfNodes: Node[] = NODE_DEFS.map((def) => {
      const nd = byName[def.name];
      const status = nd?.status;
      const isClickable = status === 'waiting_human';
      return {
        id: def.short,
        type: 'flowNode',
        position: { x: 0, y: 0 },
        // 显式 width/height 让 ReactFlow fitView 知道节点尺寸，
        // 否则只按边的 bounding box 缩放会把节点缩到 0 看不见。
        width: 160,
        height: 70,
        data: {
          label: def.label,
          assignee: nd?.assignee,
          status,
          title: def.label,
          clickable: isClickable,
          onClick: () => handleNodeClick(def.name),
        },
      };
    });

    const rfEdges: Edge[] = EDGES.map(([s, t]) => {
      const srcDef = NODE_DEFS.find((d) => d.short === s)!;
      const srcStatus = byName[srcDef.name]?.status;
      const completed = srcStatus === 'done';
      return {
        id: `${s}->${t}`,
        source: s,
        target: t,
        animated: srcStatus === 'waiting_human',
        style: {
          stroke: completed ? '#1d4ed8' : '#9ca3af',
          strokeWidth: completed ? 2 : 1.5,
          strokeDasharray: completed ? '0' : '4 4',
        },
      };
    });

    return layout(rfNodes, rfEdges);
  }, [byName, handleNodeClick]);

  return (
    <div
      style={{
        height: 520,
        background: '#fafafa',
        borderRadius: 8,
        border: '1px solid #e5e7eb',
      }}
    >
      <style>{`
        @keyframes flowdiag-pulse {
          0%, 100% { transform: scale(1); }
          50% { transform: scale(1.05); }
        }
      `}</style>
      <div
        style={{
          padding: '8px 12px',
          fontSize: 11,
          color: '#6b7280',
          display: 'flex',
          gap: 14,
          flexWrap: 'wrap',
          borderBottom: '1px solid #e5e7eb',
          background: '#fff',
        }}
      >
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              background: '#dbeafe',
              border: '2px solid #1d4ed8',
              borderRadius: 2,
              verticalAlign: 'middle',
              marginRight: 4,
            }}
          />
          已完成
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              background: '#fef3c7',
              border: '2px solid #d97706',
              borderRadius: 2,
              verticalAlign: 'middle',
              marginRight: 4,
            }}
          />
          处理中（点击进入）
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              background: '#f9fafb',
              border: '2px dashed #9ca3af',
              borderRadius: 2,
              verticalAlign: 'middle',
              marginRight: 4,
            }}
          />
          未开始
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              background: '#fee2e2',
              border: '2px solid #dc2626',
              borderRadius: 2,
              verticalAlign: 'middle',
              marginRight: 4,
            }}
          />
          拒绝
        </span>
        <span>
          <span
            style={{
              display: 'inline-block',
              width: 12,
              height: 12,
              background: '#ffedd5',
              border: '2px solid #ea580c',
              borderRadius: 2,
              verticalAlign: 'middle',
              marginRight: 4,
            }}
          />
          退回
        </span>
      </div>
      <div style={{ height: 460 }}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.15, maxZoom: 0.85, minZoom: 0.4 }}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={true}
          panOnDrag
          zoomOnScroll
          minZoom={0.3}
          maxZoom={1.6}
          onlyRenderVisibleElements={false}
          proOptions={{ hideAttribution: true }}
        >
          <Background gap={16} color="#e5e7eb" />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable />
        </ReactFlow>
      </div>
    </div>
  );
}
