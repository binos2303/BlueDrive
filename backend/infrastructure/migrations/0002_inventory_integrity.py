from django.db import migrations


FORWARD = """
ALTER TABLE infrastructure_storagenode ADD CONSTRAINT scc_node_pool_same_cluster_fk
  FOREIGN KEY (cluster_id, pool_id) REFERENCES infrastructure_serverpool (cluster_id, id);
ALTER TABLE infrastructure_storagebinding ADD CONSTRAINT scc_binding_workspace_tenant_fk
  FOREIGN KEY (tenant_id, workspace_id) REFERENCES accounts_workspace (tenant_id, id);
ALTER TABLE infrastructure_storagebinding ADD CONSTRAINT scc_binding_config_tenant_fk
  FOREIGN KEY (tenant_id, storage_config_id) REFERENCES files_storageconfig (tenant_id, id);

CREATE FUNCTION scc_check_cluster_owner() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'UPDATE' AND (OLD.kind IS DISTINCT FROM NEW.kind OR OLD.tenant_id IS DISTINCT FROM NEW.tenant_id) THEN
    RAISE EXCEPTION 'Storage cluster ownership is immutable' USING ERRCODE = '23514';
  END IF;
  IF NEW.kind = 'enterprise' AND NOT EXISTS (
      SELECT 1 FROM accounts_tenant WHERE id = NEW.tenant_id AND kind = 'business') THEN
    RAISE EXCEPTION 'Enterprise storage requires a business tenant' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scc_cluster_owner_guard BEFORE INSERT OR UPDATE ON infrastructure_storagecluster
  FOR EACH ROW EXECUTE FUNCTION scc_check_cluster_owner();

CREATE FUNCTION scc_check_storage_grant() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_tenant uuid;
BEGIN
  SELECT m.tenant_id INTO owner_tenant FROM accounts_membership m
    JOIN accounts_tenant t ON t.id = m.tenant_id
    WHERE m.id = NEW.membership_id AND t.kind = 'business';
  IF owner_tenant IS NULL OR NOT EXISTS (
      SELECT 1 FROM accounts_membership
      WHERE tenant_id = owner_tenant AND user_id = NEW.granted_by_id AND role = 'owner' AND status = 'active') THEN
    RAISE EXCEPTION 'Storage access must be delegated by the organization owner' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scc_storage_grant_guard BEFORE INSERT OR UPDATE ON infrastructure_storageaccessgrant
  FOR EACH ROW EXECUTE FUNCTION scc_check_storage_grant();

CREATE FUNCTION scc_check_storage_binding() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE tenant_kind text; cluster_kind text; cluster_tenant uuid; cluster_state text;
        cluster_provider text; verified timestamptz; config_status text; config_provider text;
BEGIN
  -- Khóa tenant để hai giao dịch không kích hoạt hai cluster khác nhau trong MVP.
  SELECT kind INTO tenant_kind FROM accounts_tenant WHERE id = NEW.tenant_id FOR UPDATE;
  SELECT kind, tenant_id, state, verified_at, provider
    INTO cluster_kind, cluster_tenant, cluster_state, verified, cluster_provider
    FROM infrastructure_storagecluster WHERE id = NEW.cluster_id FOR SHARE;
  IF (tenant_kind = 'business' AND (cluster_kind IS DISTINCT FROM 'enterprise' OR cluster_tenant IS DISTINCT FROM NEW.tenant_id))
     OR (tenant_kind = 'personal' AND cluster_kind IS DISTINCT FROM 'platform') THEN
    RAISE EXCEPTION 'Storage binding ownership mismatch' USING ERRCODE = '23514';
  END IF;
  SELECT status, provider INTO config_status, config_provider FROM files_storageconfig
    WHERE id = NEW.storage_config_id AND tenant_id = NEW.tenant_id FOR SHARE;
  IF config_provider IS DISTINCT FROM cluster_provider THEN
    RAISE EXCEPTION 'Storage binding configuration mismatch' USING ERRCODE = '23514';
  END IF;
  IF NEW.state = 'active' THEN
    IF cluster_state IS DISTINCT FROM 'ready' OR verified IS NULL OR config_status IS DISTINCT FROM 'active' THEN
      RAISE EXCEPTION 'Active binding requires verified storage' USING ERRCODE = '23514';
    END IF;
    IF tenant_kind = 'business' AND EXISTS (
        SELECT 1 FROM infrastructure_storagebinding
        WHERE tenant_id = NEW.tenant_id AND state = 'active' AND cluster_id <> NEW.cluster_id AND id <> NEW.id) THEN
      RAISE EXCEPTION 'Only one active organization storage cluster is supported' USING ERRCODE = '23514';
    END IF;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scc_storage_binding_guard BEFORE INSERT OR UPDATE ON infrastructure_storagebinding
  FOR EACH ROW EXECUTE FUNCTION scc_check_storage_binding();

CREATE FUNCTION scc_guard_tenant_kind() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  IF OLD.kind IS DISTINCT FROM NEW.kind AND (
      EXISTS (SELECT 1 FROM infrastructure_storagecluster WHERE tenant_id = OLD.id)
      OR EXISTS (SELECT 1 FROM infrastructure_storagebinding WHERE tenant_id = OLD.id)
      OR EXISTS (SELECT 1 FROM infrastructure_clusterauditevent WHERE tenant_id = OLD.id)
      OR EXISTS (SELECT 1 FROM infrastructure_storageaccessgrant g JOIN accounts_membership m ON m.id = g.membership_id WHERE m.tenant_id = OLD.id)) THEN
    RAISE EXCEPTION 'Tenant kind is referenced by storage inventory' USING ERRCODE = '23514';
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER scc_tenant_kind_guard BEFORE UPDATE OF kind ON accounts_tenant
  FOR EACH ROW EXECUTE FUNCTION scc_guard_tenant_kind();
"""

REVERSE = """
DROP TRIGGER scc_tenant_kind_guard ON accounts_tenant;
DROP FUNCTION scc_guard_tenant_kind();
DROP TRIGGER scc_storage_binding_guard ON infrastructure_storagebinding;
DROP FUNCTION scc_check_storage_binding();
DROP TRIGGER scc_storage_grant_guard ON infrastructure_storageaccessgrant;
DROP FUNCTION scc_check_storage_grant();
DROP TRIGGER scc_cluster_owner_guard ON infrastructure_storagecluster;
DROP FUNCTION scc_check_cluster_owner();
ALTER TABLE infrastructure_storagebinding DROP CONSTRAINT scc_binding_config_tenant_fk;
ALTER TABLE infrastructure_storagebinding DROP CONSTRAINT scc_binding_workspace_tenant_fk;
ALTER TABLE infrastructure_storagenode DROP CONSTRAINT scc_node_pool_same_cluster_fk;
"""


class Migration(migrations.Migration):
    dependencies = [('infrastructure', '0001_initial')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
