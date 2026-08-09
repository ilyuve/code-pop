"""Application-level exceptions."""


class CodePopException(Exception):
    """Base exception for CodePop with an HTTP status code."""

    def __init__(self, message: str, status_code: int = 500):
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class RepoNotFoundException(CodePopException):
    def __init__(self, repo_id: str):
        super().__init__(f"Repository {repo_id} not found", 404)


class RepoAlreadyExistsException(CodePopException):
    def __init__(self, git_url: str):
        super().__init__(f"该仓库地址已添加过，请勿重复索引（{git_url}）", 409)


class ValidationException(CodePopException):
    def __init__(self, message: str):
        super().__init__(message, 400)
