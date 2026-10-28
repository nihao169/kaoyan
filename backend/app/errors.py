from fastapi import HTTPException


def fail(status: int, code: str, message: str):
    raise HTTPException(status, detail={'code': code, 'message': message})


def require(value, message='记录不存在或无权访问'):
    if value is None:
        fail(404, 'NOT_FOUND', message)
    return value
