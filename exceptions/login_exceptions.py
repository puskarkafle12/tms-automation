class LoginFailedException(Exception):
    def __init__(self, message="Login failed. Invalid credentials."):
        self.message = message
        super().__init__(self.message)
