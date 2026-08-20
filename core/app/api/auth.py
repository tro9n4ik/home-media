from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import (
    verify_password, hash_password, make_session_token,
    get_current_user, COOKIE_NAME,
)
from app.models.user import User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginRequest(BaseModel):
    username: str
    password: str


class SetupRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@router.get("/me")
def me(username: str = Depends(get_current_user)):
    return {"username": username}


@router.post("/login")
async def login(request: Request, response: Response, db: Session = Depends(get_db)):
    # Принимаем и JSON и form-data
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="Неверный формат JSON")
    elif "form" in content_type:
        form = await request.form()
        data = {"username": form.get("username",""), "password": form.get("password","")}
    else:
        # Пробуем как JSON
        try:
            data = await request.json()
        except Exception:
            raise HTTPException(status_code=422, detail="Неподдерживаемый формат запроса")

    username = str(data.get("username","")).strip()
    password = str(data.get("password","")).strip()
    if not username or not password:
        raise HTTPException(status_code=422, detail="Укажите логин и пароль")

    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный логин или пароль")
    token = make_session_token(user.username)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", max_age=60*60*24*30, path="/")
    return {"ok": True, "username": user.username}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@router.get("/setup/needed")
def setup_needed(db: Session = Depends(get_db)):
    return {"needed": db.query(User).count() == 0}


@router.post("/setup")
async def setup(request: Request, db: Session = Depends(get_db)):
    if db.query(User).count() > 0:
        raise HTTPException(status_code=400, detail="Уже настроено")
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try: data = await request.json()
        except Exception: raise HTTPException(422, "Неверный формат JSON")
    elif "form" in content_type:
        form = await request.form()
        data = {"username": form.get("username",""), "password": form.get("password","")}
    else:
        try: data = await request.json()
        except Exception: raise HTTPException(422, "Неподдерживаемый формат")
    username = str(data.get("username","")).strip()
    password = str(data.get("password","")).strip()
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Пароль минимум 8 символов")
    db.add(User(username=username, password_hash=hash_password(password)))
    db.commit()
    return {"ok": True}


@router.post("/change-password")
def change_password(
    body: ChangePasswordRequest,
    username: str = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user = db.scalar(select(User).where(User.username == username))
    if not user or not verify_password(body.current_password, user.password_hash):
        raise HTTPException(status_code=401, detail="Неверный текущий пароль")
    if len(body.new_password) < 8:
        raise HTTPException(status_code=422, detail="Пароль минимум 8 символов")
    user.password_hash = hash_password(body.new_password)
    db.commit()
    return {"ok": True}
