from django.db import migrations


FOREIGN_KEYS = [
    (
        "folders",
        "Folder",
        "folder_parent_same_tenant_fk",
        ("tenant_id", "parent_id"),
        "folders",
        "Folder",
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "files",
        "File",
        "file_folder_same_tenant_fk",
        ("tenant_id", "folder_id"),
        "folders",
        "Folder",
        ("tenant_id", "id"),
        "CASCADE",
    ),
    (
        "folders",
        "Folder",
        "folder_owner_membership_fk",
        ("tenant_id", "owner_id"),
        "accounts",
        "Membership",
        ("tenant_id", "user_id"),
        "RESTRICT",
    ),
    (
        "files",
        "File",
        "file_owner_membership_fk",
        ("tenant_id", "owner_id"),
        "accounts",
        "Membership",
        ("tenant_id", "user_id"),
        "RESTRICT",
    ),
    (
        "files",
        "FileVersion",
        "version_file_same_tenant_fk",
        ("tenant_id", "file_id"),
        "files",
        "File",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "StorageLocation",
        "location_version_same_tenant_fk",
        ("tenant_id", "file_version_id"),
        "files",
        "FileVersion",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "StorageLocation",
        "location_config_same_tenant_fk",
        ("tenant_id", "storage_config_id"),
        "files",
        "StorageConfig",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "UploadSession",
        "upload_folder_same_tenant_fk",
        ("tenant_id", "target_folder_id"),
        "folders",
        "Folder",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "UploadSession",
        "upload_file_same_tenant_fk",
        ("tenant_id", "file_id"),
        "files",
        "File",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "UploadSession",
        "upload_initiator_membership_fk",
        ("tenant_id", "initiated_by_id"),
        "accounts",
        "Membership",
        ("tenant_id", "user_id"),
        "RESTRICT",
    ),
    (
        "files",
        "QuotaReservation",
        "reservation_upload_same_tenant_fk",
        ("tenant_id", "upload_session_id"),
        "files",
        "UploadSession",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "files",
        "QuotaReservation",
        "reservation_account_same_tenant_fk",
        ("tenant_id", "quota_account_id"),
        "accounts",
        "QuotaAccount",
        ("tenant_id", "id"),
        "RESTRICT",
    ),
    (
        "accounts",
        "QuotaAccount",
        "quota_member_same_tenant_fk",
        ("tenant_id", "user_id"),
        "accounts",
        "Membership",
        ("tenant_id", "user_id"),
        "RESTRICT",
    ),
]


def _constraint_sql(apps, schema_editor, spec, add):
    app, model_name, name, columns, ref_app, ref_model_name, ref_columns, on_delete = spec
    model = apps.get_model(app, model_name)
    ref_model = apps.get_model(ref_app, ref_model_name)
    quote = schema_editor.quote_name
    table = quote(model._meta.db_table)
    constraint = quote(name)

    if add:
        ref_table = quote(ref_model._meta.db_table)
        local_columns = ", ".join(quote(column) for column in columns)
        referenced_columns = ", ".join(quote(column) for column in ref_columns)
        sql = (
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"FOREIGN KEY ({local_columns}) REFERENCES {ref_table} "
            f"({referenced_columns}) ON DELETE {on_delete} "
            "DEFERRABLE INITIALLY DEFERRED"
        )
    else:
        sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"
    schema_editor.execute(sql)


def add_tenant_foreign_keys(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for spec in FOREIGN_KEYS:
        _constraint_sql(apps, schema_editor, spec, add=True)


def remove_tenant_foreign_keys(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    for spec in reversed(FOREIGN_KEYS):
        _constraint_sql(apps, schema_editor, spec, add=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_quotaaccount_quota_tenant_id_uniq"),
        ("files", "0010_remove_storageconfig_storage_global_provider_uniq_and_more"),
        ("folders", "0009_alter_folder_tenant"),
    ]

    operations = [
        migrations.RunPython(
            add_tenant_foreign_keys,
            reverse_code=remove_tenant_foreign_keys,
        ),
    ]
