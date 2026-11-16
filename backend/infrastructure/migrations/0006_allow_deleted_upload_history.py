from django.db import migrations


# Giữ guard công bố cho file đang tồn tại; cho phép lưu lịch sử sau xóa vĩnh viễn.
FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION scc_check_pinned_file_target() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE owner_kind text; owner_tenant uuid; target_revision bigint; tenant_kind text;
        detached_history boolean := false;
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
{history_guard}
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
  IF NEW.state IN ('available','completed') {history_exception}AND NOT EXISTS (
   SELECT 1 FROM files_fileversion v JOIN files_storagelocation l ON l.file_version_id=v.id
   WHERE v.file_id=NEW.file_id AND v.state='available' AND l.state='available'
    AND l.storage_connection_id=NEW.storage_connection_id AND l.storage_config_id=NEW.storage_config_id) THEN
   RAISE EXCEPTION 'Publication must use the pinned upload target' USING ERRCODE='23514';
  END IF;
 END IF;
 RETURN NEW;
END $$;
"""


HISTORY_GUARD = """
  IF TG_OP = 'UPDATE' AND OLD.state IN ('available','completed') THEN
   IF OLD.state = NEW.state AND OLD.file_id IS NULL AND NEW.file_id IS NULL THEN
    detached_history := true;
   ELSIF OLD.file_id IS DISTINCT FROM NEW.file_id THEN
    IF OLD.state = NEW.state AND OLD.file_id IS NOT NULL AND NEW.file_id IS NULL AND NOT EXISTS (
     SELECT 1 FROM files_fileversion WHERE file_id=OLD.file_id) THEN
     detached_history := true;
    ELSE
     RAISE EXCEPTION 'Successful upload history cannot change its file before permanent deletion' USING ERRCODE='23514';
    END IF;
   END IF;
  END IF;
"""

FORWARD = FUNCTION_SQL.format(history_guard=HISTORY_GUARD, history_exception="AND NOT detached_history ")
REVERSE = FUNCTION_SQL.format(history_guard="", history_exception="")


class Migration(migrations.Migration):
    dependencies = [('infrastructure', '0005_telemetry_snapshots_and_alerts'), ('files', '0017_pin_storage_targets')]
    operations = [migrations.RunSQL(FORWARD, REVERSE)]
