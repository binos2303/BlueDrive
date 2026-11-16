from django.db import migrations, models


FORWARD = """
CREATE OR REPLACE FUNCTION scc_probe_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE data_bucket text;
BEGIN
 SELECT bucket INTO data_bucket FROM infrastructure_storageconnectionrevision WHERE id=NEW.connection_id;
 IF NEW.object_key IS DISTINCT FROM 'staging/' || replace(NEW.id::text,'-','') OR
  (NEW.mode='lab' AND NEW.bucket IS DISTINCT FROM 'bluedrive-scc-' || replace(NEW.id::text,'-','')) OR
  (NEW.mode='runtime' AND (NEW.bucket IS DISTINCT FROM data_bucket OR NEW.bucket_created)) THEN
  RAISE EXCEPTION 'Probe fixture identity must be server-owned and match its qualification mode' USING ERRCODE='23514';
 END IF;
 IF TG_OP='UPDATE' AND ((to_jsonb(OLD) - ARRAY['state','bucket_created','object_version_id','checks','error_code','completed_at','cleanup_generation']) IS DISTINCT FROM
  (to_jsonb(NEW) - ARRAY['state','bucket_created','object_version_id','checks','error_code','completed_at','cleanup_generation']) OR (OLD.bucket_created AND NOT NEW.bucket_created) OR NEW.cleanup_generation < OLD.cleanup_generation) THEN
  RAISE EXCEPTION 'Probe ownership is immutable' USING ERRCODE='23514';
 END IF;
 RETURN NEW;
END $$;
"""

REVERSE = """
CREATE OR REPLACE FUNCTION scc_probe_identity_guard() RETURNS trigger LANGUAGE plpgsql AS $$
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
"""


class Migration(migrations.Migration):
    dependencies = [('infrastructure','0006_allow_deleted_upload_history')]
    operations = [
        migrations.AddField(model_name='storageconnectionprobe', name='mode',
            field=models.CharField(max_length=12, choices=[('lab','LAB provisioning'),('runtime','Application runtime')], default='lab')),
        migrations.AlterField(model_name='storageconnectionprobe', name='bucket', field=models.CharField(max_length=63)),
        migrations.AddConstraint(model_name='storageconnectionprobe', constraint=models.CheckConstraint(condition=models.Q(mode__in=['lab','runtime']), name='scc_probe_mode_valid')),
        migrations.AddConstraint(model_name='storageconnectionprobe', constraint=models.UniqueConstraint(fields=['bucket'], condition=models.Q(mode='lab'), name='scc_lab_probe_bucket_uniq')),
        migrations.RunSQL(FORWARD, REVERSE),
    ]
