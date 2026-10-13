from django.db import migrations


def update_constraints(apps, schema_editor, add):
    if schema_editor.connection.vendor != "postgresql":
        return

    Share = apps.get_model("sharing", "Share")
    File = apps.get_model("files", "File")
    Folder = apps.get_model("folders", "Folder")
    Membership = apps.get_model("accounts", "Membership")
    quote = schema_editor.quote_name

    constraints = [
        (
            Share,
            "share_file_same_tenant_fk",
            ("tenant_id", "file_id"),
            File,
            ("tenant_id", "id"),
            "CASCADE",
        ),
        (
            Share,
            "share_folder_same_tenant_fk",
            ("tenant_id", "folder_id"),
            Folder,
            ("tenant_id", "id"),
            "CASCADE",
        ),
        (
            Share,
            "share_owner_membership_fk",
            ("tenant_id", "owner_id"),
            Membership,
            ("tenant_id", "user_id"),
            "RESTRICT",
        ),
    ]
    if not add:
        constraints.reverse()

    for model, name, columns, ref_model, ref_columns, on_delete in constraints:
        table = quote(model._meta.db_table)
        constraint = quote(name)
        if add:
            local_columns = ", ".join(quote(column) for column in columns)
            referenced_columns = ", ".join(
                quote(column) for column in ref_columns
            )
            sql = (
                f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
                f"FOREIGN KEY ({local_columns}) REFERENCES "
                f"{quote(ref_model._meta.db_table)} ({referenced_columns}) "
                f"ON DELETE {on_delete} DEFERRABLE INITIALLY DEFERRED"
            )
        else:
            sql = f"ALTER TABLE {table} DROP CONSTRAINT {constraint}"
        schema_editor.execute(sql)


def add_constraints(apps, schema_editor):
    update_constraints(apps, schema_editor, add=True)


def remove_constraints(apps, schema_editor):
    update_constraints(apps, schema_editor, add=False)


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0003_quotaaccount_quota_tenant_id_uniq"),
        ("files", "0011_add_tenant_composite_foreign_keys"),
        ("folders", "0009_alter_folder_tenant"),
        ("sharing", "0011_alter_share_tenant"),
    ]

    operations = [
        migrations.RunPython(add_constraints, reverse_code=remove_constraints),
    ]
