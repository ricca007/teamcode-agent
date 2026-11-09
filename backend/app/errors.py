class Role2Error(Exception):
    """Base error for the role-2 subsystem."""


class InvalidTaskError(Role2Error):
    pass


class InvalidPathError(Role2Error):
    pass


class PermissionDeniedError(Role2Error):
    pass


class SessionNotFoundError(Role2Error):
    pass


class InvalidStateTransitionError(Role2Error):
    pass


class TaskAlreadyRunningError(Role2Error):
    pass


class WorkspaceError(Role2Error):
    pass


class AdapterError(Role2Error):
    pass
