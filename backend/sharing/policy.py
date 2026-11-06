"""Deprecated compatibility helpers; sharing is no longer limited by file size.

Authorization and recipient eligibility remain enforced by share endpoints.
"""

def file_share_allowed(file):
    return True


def folder_share_allowed(folder):
    return True
