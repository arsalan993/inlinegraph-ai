"use client";

import { Background, Controls, Edge, MiniMap, Node, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";

type Conversation = {
  id: string;
  messages: { id: string; role: string; content: string; passages: { id: string; content: string }[] }[];
  branches: {
    id: string;
    source_passage_id: string;
    user_instruction: string;
    status: string;
    accepted: boolean | null;
    messages: { id: string; role: string; content: string }[];
    selections?: { text: string; source_passage_ids: string[] }[];
  }[];
  context_sources?: {
    target_message_id: string;
    source_branch_id: string;
    source_branch_message_ids: string[];
    source_status: string;
    source_accepted: boolean | null;
  }[];
};

const edgeStyle = { stroke: "#b8c9cc" };
const contextEdgeStyle = { stroke: "#6558d3", strokeDasharray: "7 4", strokeWidth: 2.2 };

export default function GraphView({ conversation, onSelectBranch }: { conversation: Conversation; onSelectBranch: (id: string) => void }) {
  const nodes: Node[] = [];
  const edges: Edge[] = [];
  const passagePositions = new Map<string, { x: number; y: number }>();
  const messagePositions = new Map<string, { x: number; y: number }>();
  let turnIndex = -1;
  let lastQuestionId: string | null = null;

  for (const message of conversation.messages) {
    if (message.role === "user") {
      turnIndex += 1;
      lastQuestionId = message.id;
      const y = 70 + turnIndex * 350;
      messagePositions.set(message.id, { x: 40, y });
      nodes.push({
        id: message.id,
        type: "default",
        position: { x: 40, y },
        data: { label: `Question\n${message.content.slice(0, 90)}` },
        className: "graph-node graph-question",
      });
      continue;
    }

    const answerY = 70 + Math.max(turnIndex, 0) * 350;
    messagePositions.set(message.id, { x: 340, y: answerY });
    if (lastQuestionId) {
      edges.push({ id: `${lastQuestionId}-${message.id}`, source: lastQuestionId, target: message.id, label: "answers", style: edgeStyle });
    }
    nodes.push({
      id: message.id,
      type: "default",
      position: { x: 340, y: answerY },
      data: { label: `Main answer\n${message.content.slice(0, 105)}` },
      className: "graph-node graph-answer",
    });

    message.passages.forEach((passage, passageIndex) => {
      const position = { x: 660, y: answerY + passageIndex * 145 };
      passagePositions.set(passage.id, position);
      nodes.push({
        id: passage.id,
        type: "default",
        position,
        data: { label: passage.content.slice(0, 105) },
        className: "graph-node graph-passage",
      });
      edges.push({ id: `${message.id}-${passage.id}`, source: message.id, target: passage.id, label: "contains", style: edgeStyle });
    });
  }

  const branchAnswerPositions = new Map<string, { x: number; y: number; branchId: string }>();
  conversation.branches.forEach((branch, branchIndex) => {
    const selections = branch.selections?.length ? branch.selections : [{ text: branch.user_instruction, source_passage_ids: [branch.source_passage_id] }];
    const sourceIds = [...new Set(selections.flatMap((selection) => selection.source_passage_ids))];
    const anchor = sourceIds.map((id) => passagePositions.get(id)).find(Boolean) || { x: 660, y: 70 + (turnIndex + branchIndex + 1) * 350 };
    selections.forEach((selection, selectionIndex) => {
      const selectionNodeId = `${branch.id}:selection:${selectionIndex}`;
      nodes.push({
        id: selectionNodeId,
        type: "default",
        position: { x: 850, y: anchor.y + selectionIndex * 105 },
        data: { label: `Selected text\n${selection.text.slice(0, 92)}`, branchId: branch.id },
        className: "graph-node graph-selection",
        style: { cursor: "pointer" },
      });
      for (const sourceId of selection.source_passage_ids) {
        if (passagePositions.has(sourceId)) {
          edges.push({ id: `${sourceId}-${selectionNodeId}`, source: sourceId, target: selectionNodeId, label: "selected from", style: { stroke: "#13a391", strokeDasharray: "4 3" } });
        }
      }
    });
    const questionPosition = { x: 1110, y: anchor.y + Math.max(1, selections.length) * 105 };
    nodes.push({
      id: branch.id,
      type: "default",
      position: questionPosition,
      data: { label: `Branch question · ${branch.status.replaceAll("_", " ")}\n${branch.user_instruction.slice(0, 78)}`, branchId: branch.id },
      className: "graph-node graph-branch graph-branch-question",
      style: { cursor: "pointer" },
    });
    for (let selectionIndex = 0; selectionIndex < selections.length; selectionIndex += 1) {
      const selectionNodeId = `${branch.id}:selection:${selectionIndex}`;
      edges.push({ id: `${selectionNodeId}-${branch.id}`, source: selectionNodeId, target: branch.id, label: "question about", style: { stroke: "#13a391", strokeDasharray: "4 3" } });
    }

    let previousNode = branch.id;
    let replyIndex = 0;
    for (const [messageIndex, branchMessage] of branch.messages.entries()) {
      if (messageIndex === 0 && branchMessage.role === "user" && branchMessage.content === branch.user_instruction) continue;
      const y = questionPosition.y + 125 + replyIndex * 145;
      const nodeId = branchMessage.id;
      const isAssistant = branchMessage.role === "assistant";
      nodes.push({
        id: nodeId,
        type: "default",
        position: { x: 1410, y },
        data: { label: `${isAssistant ? "Branch answer" : "Branch follow-up"}\n${branchMessage.content.slice(0, 92)}`, branchId: branch.id },
        className: `graph-node ${isAssistant ? "graph-branch-answer" : "graph-branch-followup"}`,
        style: { cursor: "pointer" },
      });
      if (isAssistant) branchAnswerPositions.set(nodeId, { x: 1410, y, branchId: branch.id });
      edges.push({ id: `${previousNode}-${nodeId}`, source: previousNode, target: nodeId, label: isAssistant ? "answers" : "continues", style: { stroke: "#9ac5b9" } });
      previousNode = nodeId;
      replyIndex += 1;
    }
  });

  for (const usage of conversation.context_sources || []) {
    const targetExists = messagePositions.has(usage.target_message_id);
    if (!targetExists) continue;
    const assistantSources = usage.source_branch_message_ids.filter((id) => branchAnswerPositions.has(id)).slice(-1);
    if (assistantSources.length) {
      for (const sourceId of assistantSources) {
        edges.push({
          id: `context-${sourceId}-${usage.target_message_id}`,
          source: sourceId,
          target: usage.target_message_id,
          label: "included as context",
          style: contextEdgeStyle,
          markerEnd: { type: "arrowclosed", color: "#6558d3" },
        });
      }
    } else if (conversation.branches.some((branch) => branch.id === usage.source_branch_id)) {
      edges.push({
        id: `context-${usage.source_branch_id}-${usage.target_message_id}`,
        source: usage.source_branch_id,
        target: usage.target_message_id,
        label: "included as context",
        style: contextEdgeStyle,
        markerEnd: { type: "arrowclosed", color: "#6558d3" },
      });
    }
  }

  return (
    <div className="graph-shell">
      <div className="graph-toolbar">
        <div><span className="eyebrow">CONVERSATION STRUCTURE</span><h2>Explore the connections</h2></div>
        <span className="graph-legend"><i /> Answer <i className="legend-passage" /> Passage <i className="legend-selection" /> Selection <i className="legend-branch" /> Branch <i className="legend-context" /> Context included</span>
      </div>
      <div className="graph-canvas">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          fitView
          fitViewOptions={{ padding: 0.18 }}
          nodesDraggable
          nodesConnectable={false}
          onNodeClick={(_, node) => {
            const branchId = (node.data as { branchId?: string }).branchId;
            if (branchId) onSelectBranch(branchId);
          }}
        >
          <Background color="#dce7e6" gap={22} />
          <Controls />
          <MiniMap nodeColor={(node) => node.className?.includes("branch") ? "#14a38e" : node.className?.includes("passage") ? "#d8ebe8" : node.className?.includes("question") ? "#f1e7d7" : "#e4e9f2"} />
        </ReactFlow>
      </div>
    </div>
  );
}
