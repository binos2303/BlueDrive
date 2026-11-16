from django.db import migrations


FORWARD = """
ALTER TABLE files_uploadsession ADD CONSTRAINT scc_upload_config_tenant_fk
 FOREIGN KEY (tenant_id,storage_config_id) REFERENCES files_storageconfig(tenant_id,id);

CREATE FUNCTION scc_immutable_connection() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.verification_generation < OLD.verification_generation THEN
  RAISE EXCEPTION 'Connection verification generation cannot decrease' USING ERRCODE='23514';
 END IF;
 IF (to_jsonb(OLD) - ARRAY['state','verification_generation','verification_started_at','read_verified_at','verified_at','last_error_code']) IS DISTINCT FROM
    (to_jsonb(NEW) - ARRAY['state','verification_generation','verification_started_at','read_verified_at','verified_at','last_error_code']) THEN
  RAISE EXCEPTION 'Connection targets are immutable; register a new revision' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER scc_connection_target_guard BEFORE UPDATE ON infrastructure_storageconnectionrevision
 FOR EACH ROW EXECUTE FUNCTION scc_immutable_connection();

CREATE FUNCTION scc_check_pinned_file_target() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_kind text; owner_tenant uuid; target_revision bigint; tenant_kind text;
BEGIN
 IF TG_TABLE_NAME = 'files_uploadsession' THEN
  IF TG_OP = 'UPDATE' AND (OLD.storage_connection_id IS DISTINCT FROM NEW.storage_connection_id OR
    OLD.storage_config_id IS DISTINCT FROM NEW.storage_config_id OR OLD.endpoint_config_version IS DISTINCT FROM NEW.endpoint_config_version) THEN
   RAISE EXCEPTION 'Upload storage target is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.storage_connection_id IS NULL THEN
   IF NEW.storage_config_id IS NOT NULL OR NEW.endpoint_config_version IS NOT NULL THEN
    RAISE EXCEPTION 'Upload target must be complete or legacy' USING ERRCODE='23514';
   END IF;
   RETURN NEW;
  END IF;
 ELSE
  IF TG_OP = 'UPDATE' AND OLD.storage_connection_id IS DISTINCT FROM NEW.storage_connection_id THEN
   RAISE EXCEPTION 'Published storage connection is immutable' USING ERRCODE='23514';
  END IF;
  IF NEW.storage_connection_id IS NULL THEN RETURN NEW; END IF;
  IF TG_OP = 'UPDATE' AND (OLD.object_ref IS DISTINCT FROM NEW.object_ref OR OLD.storage_config_id IS DISTINCT FROM NEW.storage_config_id OR OLD.provider_version_id IS DISTINCT FROM NEW.provider_version_id) THEN
   RAISE EXCEPTION 'Published object identity is immutable' USING ERRCODE='23514';
  END IF;
 END IF;
 SELECT c.kind,c.tenant_id,r.revision INTO owner_kind,owner_tenant,target_revision
  FROM infrastructure_storageconnectionrevision r JOIN infrastructure_storagecluster c ON c.id=r.cluster_id
  WHERE r.id=NEW.storage_connection_id;
 SELECT kind INTO tenant_kind FROM accounts_tenant WHERE id=NEW.tenant_id;
 IF (tenant_kind='business' AND (owner_kind IS DISTINCT FROM 'enterprise' OR owner_tenant IS DISTINCT FROM NEW.tenant_id))
  OR (tenant_kind='personal' AND owner_kind IS DISTINCT FROM 'platform') THEN
  RAISE EXCEPTION 'Pinned storage ownership mismatch' USING ERRCODE='23514';
 END IF;
 IF TG_TABLE_NAME = 'files_uploadsession' THEN
  IF NEW.storage_config_id IS NULL OR NEW.endpoint_config_version IS DISTINCT FROM target_revision THEN
   RAISE EXCEPTION 'Pinned storage version mismatch' USING ERRCODE='23514';
  END IF;
  IF NEW.state IN ('available','completed') AND NOT EXISTS (
   SELECT 1 FROM files_fileversion v JOIN files_storagelocation l ON l.file_version_id=v.id
   WHERE v.file_id=NEW.file_id AND v.state='available' AND l.state='available'
    AND l.storage_connection_id=NEW.storage_connection_id AND l.storage_config_id=NEW.storage_config_id) THEN
   RAISE EXCEPTION 'Publication must use the pinned upload target' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER scc_upload_target_guard BEFORE INSERT OR UPDATE ON files_uploadsession
 FOR EACH ROW EXECUTE FUNCTION scc_check_pinned_file_target();
CREATE TRIGGER scc_location_target_guard BEFORE INSERT OR UPDATE ON files_storagelocation
 FOR EACH ROW EXECUTE FUNCTION scc_check_pinned_file_target();

CREATE FUNCTION scc_binding_connection_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE target_cluster uuid; target_kind text; target_state text; cluster_state text;
BEGIN
 IF NEW.connection_id IS NULL THEN RETURN NEW; END IF;
 SELECT r.cluster_id,c.kind,r.state,c.state INTO target_cluster,target_kind,target_state,cluster_state
  FROM infrastructure_storageconnectionrevision r JOIN infrastructure_storagecluster c ON c.id=r.cluster_id WHERE r.id=NEW.connection_id;
 IF TG_TABLE_NAME='infrastructure_platformstoragebinding' THEN
  IF target_kind IS DISTINCT FROM 'platform' OR target_state IS DISTINCT FROM 'ready' OR cluster_state IS DISTINCT FROM 'ready' THEN
   RAISE EXCEPTION 'Platform binding requires verified Platform storage' USING ERRCODE='23514';
  END IF;
 ELSE
  IF target_cluster IS DISTINCT FROM NEW.cluster_id OR (NEW.state='active' AND target_state IS DISTINCT FROM 'ready') THEN
   RAISE EXCEPTION 'Binding connection does not match verified cluster' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER scc_binding_connection_check BEFORE INSERT OR UPDATE ON infrastructure_storagebinding
 FOR EACH ROW EXECUTE FUNCTION scc_binding_connection_guard();
CREATE TRIGGER scc_platform_connection_check BEFORE INSERT OR UPDATE ON infrastructure_platformstoragebinding
 FOR EACH ROW EXECUTE FUNCTION scc_binding_connection_guard();

CREATE FUNCTION scc_probe_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF NEW.bucket !~ '^bluedrive-scc-[0-9a-f]{32}$' OR NEW.object_key !~ '^staging/[0-9a-f]{32}$' THEN
  RAISE EXCEPTION 'Probe fixture identity must be server-owned' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND ((to_jsonb(OLD) - ARRAY['state','bucket_created','object_version_id','checks','error_code','completed_at','cleanup_generation']) IS DISTINCT FROM
  (to_jsonb(NEW) - ARRAY['state','bucket_created','object_version_id','checks','error_code','completed_at','cleanup_generation']) OR (OLD.bucket_created AND NOT NEW.bucket_created) OR NEW.cleanup_generation < OLD.cleanup_generation) THEN
  RAISE EXCEPTION 'Probe ownership is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER scc_probe_owned_fixture BEFORE INSERT OR UPDATE ON infrastructure_storageconnectionprobe
 FOR EACH ROW EXECUTE FUNCTION scc_probe_identity_guard();

CREATE FUNCTION scc_pinned_tenant_kind_guard() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
 IF OLD.kind IS DISTINCT FROM NEW.kind AND (
  EXISTS (SELECT 1 FROM files_uploadsession WHERE tenant_id=OLD.id AND storage_connection_id IS NOT NULL)
  OR EXISTS (SELECT 1 FROM files_storagelocation WHERE tenant_id=OLD.id AND storage_connection_id IS NOT NULL)) THEN
  RAISE EXCEPTION 'Tenant kind is referenced by pinned file storage' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
CREATE TRIGGER scc_pinned_tenant_kind_check BEFORE UPDATE OF kind ON accounts_tenant
 FOR EACH ROW EXECUTE FUNCTION scc_pinned_tenant_kind_guard();
"""

REVERSE = """
DROP TRIGGER scc_pinned_tenant_kind_check ON accounts_tenant;
DROP FUNCTION scc_pinned_tenant_kind_guard();
DROP TRIGGER scc_probe_owned_fixture ON infrastructure_storageconnectionprobe;
DROP FUNCTION scc_probe_identity_guard();
DROP TRIGGER scc_platform_connection_check ON infrastructure_platformstoragebinding;
DROP TRIGGER scc_binding_connection_check ON infrastructure_storagebinding;
DROP FUNCTION scc_binding_connection_guard();
DROP TRIGGER scc_location_target_guard ON files_storagelocation;
DROP TRIGGER scc_upload_target_guard ON files_uploadsession;
DROP FUNCTION scc_check_pinned_file_target();
DROP TRIGGER scc_connection_target_guard ON infrastructure_storageconnectionrevision;
DROP FUNCTION scc_immutable_connection();
ALTER TABLE files_uploadsession DROP CONSTRAINT scc_upload_config_tenant_fk;
"""


class Migration(migrations.Migration):
    dependencies = [('infrastructure','0003_connection_revisions'),('files','0017_pin_storage_targets')]
    operations = [migrations.RunSQL(FORWARD,REVERSE)]
