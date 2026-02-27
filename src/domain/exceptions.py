class AppError(Exception):
    """사용자에게 안내할 수 있는 앱 레벨 에러"""
    def __init__(self, user_message: str, debug_message: str = ""):
        super().__init__(debug_message or user_message)
        self.user_message = user_message
        self.debug_message = debug_message or user_message