from .models import Share


def get_folder_ancestor_ids(folder):
    """
    Lấy folder hiện tại và toàn bộ folder cha.

    Nếu user được share một folder cha, họ mặc nhiên có quyền
    trên folder con và file bên trong.
    """
    folder_ids = []
    current = folder

    while current is not None:
        folder_ids.append(current.id)
        current = current.parent

    return folder_ids


def get_receiver_share_for_folder(folder, user):
    """
    Trả về quyền gần nhất cấp cho user trên folder này hoặc folder cha.
    Folder con được ưu tiên hơn folder cha.
    """
    folder_ids = get_folder_ancestor_ids(folder)

    shares = Share.objects.filter(
        receiver=user,
        folder_id__in=folder_ids,
    )

    shares_by_folder = {
        share.folder_id: share
        for share in shares
    }

    # folder_ids bắt đầu từ folder hiện tại, nên quyền gần nhất được ưu tiên.
    for folder_id in folder_ids:
        share = shares_by_folder.get(folder_id)

        if share is not None:
            return share

    return None


def get_receiver_share_for_file(drive_file, user):
    """
    File có thể được cấp quyền trực tiếp hoặc thừa kế quyền từ folder cha.
    Quyền trực tiếp được ưu tiên.
    """
    direct_share = Share.objects.filter(
        receiver=user,
        file=drive_file,
    ).first()

    if direct_share is not None:
        return direct_share

    if drive_file.folder_id is None:
        return None

    return get_receiver_share_for_folder(
        drive_file.folder,
        user,
    )