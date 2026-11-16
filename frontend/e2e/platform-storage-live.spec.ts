import { test, expect } from "./mocked-api";

const endpoint = "/accounts/api/admin/storage/platform/live/";

test("Platform Packet Tracer style dashboard draws real nodes and guides safe expansion", async ({ page, api }) => {
  api.admin = true;
  api.override(endpoint, async (route) => route.fulfill({ json: {
    source: "seaweedfs_master", observed_at: "2026-11-13T08:59:00+07:00", master_online: true, s3_gateway_responding: true,
    nodes: [
      { id: "volume", address: "volume:8080", online: true, datacenter: "platform", rack: "lab", max_slots: 32, free_slots: 31, volumes: 1, stored_bytes: 1048576 },
      { id: "volume2", address: "volume2:8080", online: true, datacenter: "platform", rack: "lab", max_slots: 32, free_slots: 32, volumes: 0, stored_bytes: 0 },
      { id: "volume3", address: "", online: false, datacenter: "", rack: "", max_slots: 0, free_slots: 0, volumes: 0, stored_bytes: null },
    ],
    online_nodes: 2, volume_slots: 64, free_slots: 63, used_volume_slots: 1, stored_volume_bytes: 1048576,
    physical_disk_bytes_available: null, error_code: null, routing_enabled: true, binding_ready: true, binding_revision: 2,
    docker_metrics: { state: "fresh", sampled_at: "2026-11-13T08:59:00+07:00", containers: {
      volume: { docker_health: "healthy", cpu_percent: 1.25, memory_used_bytes: 52428800,
        memory_limit_bytes: 536870912, network_rx_bytes: 1024, network_tx_bytes: 2048,
        disk_total_bytes: 10737418240, disk_available_bytes: 5368709120 },
      filer: { docker_health: "healthy", cpu_percent: 0.1, memory_used_bytes: 1048576,
        memory_limit_bytes: 1073741824, network_rx_bytes: 100, network_tx_bytes: 200,
        disk_total_bytes: null, disk_available_bytes: null },
    } },
    alerts: [{ code: "node_unregistered", severity: "warning", title: "volume3 not registered",
      detail: "The expected Volume Server is absent from Master topology." }],
    collections: [{ name: "bluedrive-dev", unique_volumes: 1, volume_copies: 1, stored_bytes: 1048576 }],
  } }));
  await page.goto("/admin/infrastructure/topology");
  await expect(page.getByRole("heading", { name: "Platform storage" })).toBeVisible();
  await expect(page.getByText("2 / 3", { exact: true })).toBeVisible();
  await expect(page.getByText("1.0 MiB", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("button", { name: "Connect existing storage" })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "Prepare for new uploads" })).toHaveCount(0);
  await expect(page.getByRole("region", { name: "Platform storage node topology" })).toBeVisible();
  await expect(page.getByRole("complementary", { name: "Storage node details" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Add Node" })).toBeVisible();
  await expect(page.getByText("SeaweedFS Master", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Volume node inventory" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Operational health" })).toBeVisible();
  await expect(page.getByText("volume3 not registered")).toBeVisible();
  await expect(page.getByRole("heading", { name: "Collection inventory" })).toBeVisible();
  await expect(page.getByText("Unique volume IDs")).toBeHidden();
  await page.getByText("Collection inventory", { exact: true }).click();
  await expect(page.getByText("Unique volume IDs")).toBeVisible();
  await expect(page.getByText("Docker metrics: Live sample", { exact: true })).toBeVisible();
  await expect(page.getByText("1.25%", { exact: true }).first()).toBeVisible();
  await page.getByRole("button", { name: "Add Node" }).click();
  const dialog = page.getByRole("dialog", { name: "Add storage node" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("volume4", { exact: false }).first()).toBeVisible();
  await expect(dialog.getByText("Run on the Platform host, then refresh to verify registration.")).toBeVisible();
  await expect(dialog.getByText("add-platform-volume.ps1", { exact: false })).toBeVisible();
  await dialog.getByRole("button", { name: "Close" }).first().click();
  await expect(dialog).toHaveCount(0);
});
