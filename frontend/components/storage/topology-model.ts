import type { Edge, Node } from "@xyflow/react";
import type { StorageHost, StorageTopologySnapshot } from "@/lib/storage-control-service";

export type HostFlowNode = Node<{ inventory: StorageHost; diskCount: number; inspect: (id: string) => void }, "host">;
export type PoolFlowNode = Node<{ label: string; count: number }, "pool">;
export type StorageFlowNode = HostFlowNode | PoolFlowNode;
export const HOST_WIDTH = 240;
export const HOST_HEIGHT = 148;

/** Pool là quan hệ inventory; layout không tạo/chuyển node sang pool khác. */
export function topologyGraph(snapshot: StorageTopologySnapshot, inspect: (id: string) => void, saved = snapshot.layout.positions) {
  const groups = snapshot.pools.map((pool) => ({ id: pool.id, name: pool.name, members: snapshot.nodes.filter((node) => node.pool_id === pool.id) }));
  const unassigned = snapshot.nodes.filter((node) => node.pool_id === null || !snapshot.pools.some((pool) => pool.id === node.pool_id));
  if (unassigned.length) groups.push({ id: "unassigned", name: "Unassigned nodes", members: unassigned });
  const disks = new Map<string, number>();
  for (const disk of snapshot.disks) disks.set(disk.node_id, (disks.get(disk.node_id) ?? 0) + 1);
  const nodes: StorageFlowNode[] = [];
  const edges: Edge[] = [];
  let groupX = 0;
  let adjusted = 0;
  for (const group of groups) {
    const cols = Math.min(10, Math.max(1, Math.ceil(Math.sqrt(group.members.length * 1.5))));
    const width = cols * (HOST_WIDTH + 24) + 24;
    const height = Math.max(1, Math.ceil(group.members.length / cols)) * (HOST_HEIGHT + 24) + 80;
    const parent = `pool:${group.id}`;
    nodes.push({ id: parent, type: "pool", position: { x: groupX, y: 0 }, data: { label: group.name, count: group.members.length }, style: { width, height }, draggable: false, selectable: false, focusable: false, connectable: false, deletable: false });
    group.members.forEach((inventory, index) => {
      const initial = { x: 24 + (index % cols) * (HOST_WIDTH + 24), y: 60 + Math.floor(index / cols) * (HOST_HEIGHT + 24) };
      const stored = saved[inventory.id];
      const position = stored ? { x: Math.max(12, Math.min(width - HOST_WIDTH - 12, stored.x)), y: Math.max(48, Math.min(height - HOST_HEIGHT - 12, stored.y)) } : initial;
      if (stored && (stored.x !== position.x || stored.y !== position.y)) adjusted++;
      nodes.push({ id: inventory.id, type: "host", parentId: parent, extent: "parent", position, width: HOST_WIDTH, height: HOST_HEIGHT,
        data: { inventory, diskCount: disks.get(inventory.id) ?? 0, inspect }, dragHandle: ".storage-drag-handle", focusable: false, connectable: false, deletable: false });
      edges.push({ id: `${parent}:${inventory.id}`, source: parent, target: inventory.id, selectable: false, deletable: false, type: "smoothstep", style: { stroke: "var(--border-strong)", strokeWidth: 1 } });
    });
    groupX += width + 64;
  }
  return { nodes, edges, adjusted };
}

export function layoutPositions(nodes: StorageFlowNode[]) {
  return Object.fromEntries(nodes.filter((node) => node.type === "host").map((node) => [node.id, { x: node.position.x, y: node.position.y }]));
}

export function matchesHost(node: StorageHost, query: string, pool: string, status: string) {
  const text = [node.hostname, node.id, ...node.private_ips, ...Object.values(node.labels)].join(" ").toLowerCase();
  return (!query || text.includes(query.trim().toLowerCase())) && (pool === "all" || (pool === "unassigned" ? !node.pool_id : pool === node.pool_id)) && (status === "all" || node.inventory_status === status);
}
