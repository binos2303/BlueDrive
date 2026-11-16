from collections import defaultdict

from .models import Folder


def folder_subtree(folder, *, owner=None, include_deleted=False):
    """Traverse one tenant/workspace; callers must authorize the root first."""
    result = [folder]
    seen = {folder.pk}
    filters = {"tenant_id": folder.tenant_id, "workspace_id": folder.workspace_id}
    if owner is not None:
        filters["owner"] = owner
    if not include_deleted:
        filters["deleted_at__isnull"] = True
    frontier = [folder.pk]
    while frontier:
        children = defaultdict(list)
        # Bound IN parameters even when a directory has many thousands of children.
        for offset in range(0, len(frontier), 1000):
            for child in Folder.objects.filter(parent_id__in=frontier[offset:offset + 1000], **filters).order_by("pk"):
                children[child.parent_id].append(child)
        next_frontier = []
        for parent_id in frontier:
            for child in children[parent_id]:
                if child.pk not in seen:
                    seen.add(child.pk)
                    result.append(child)
                    next_frontier.append(child.pk)
        frontier = next_frontier
    return result
