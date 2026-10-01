from __future__ import annotations

from datetime import datetime
from typing import Any

from litestar import Controller, MediaType, Request, get, post
from litestar.enums import RequestEncodingType
from litestar.params import Body
from litestar.response import Redirect, Template
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from charclamp.domain.models import BurnShift, Clamp, OxygenReading, User, utcnow
from charclamp.domain.rules import (
    RuleError,
    assert_can_set_clamp_status,
    can_mark_clamp_drawn,
    validate_oxygen_reading,
)
from charclamp.infra.db import SessionLocal
from charclamp.infra.security import verify_password

STATUS_LABELS = {
    Clamp.STATUS_STACKED: "已码窑",
    Clamp.STATUS_BURNING: "焖烧中",
    Clamp.STATUS_DRAWN: "已出炭",
}


def _set_flash(request: Request, message: str, category: str = "ok") -> None:
    data = dict(request.session or {})
    data["flash"] = message
    data["flash_cat"] = category
    request.set_session(data)


def _pop_flash(request: Request) -> tuple[str | None, str | None]:
    data = dict(request.session or {})
    message = data.pop("flash", None)
    category = data.pop("flash_cat", None)
    if message is not None or category is not None:
        request.set_session(data)
    return message, category


def _parse_optional_int(raw: str | None) -> int | None:
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def _load_timeline_context(clamp_id: int | None = None) -> dict[str, Any]:
    async with SessionLocal() as db:
        clamps = list(
            (
                await db.execute(
                    select(Clamp)
                    .options(
                        selectinload(Clamp.site),
                        selectinload(Clamp.shifts),
                        selectinload(Clamp.oxygen_readings),
                    )
                    .order_by(Clamp.code)
                )
            )
            .scalars()
            .all()
        )
        query = (
            select(BurnShift)
            .options(selectinload(BurnShift.clamp).selectinload(Clamp.site))
            .order_by(BurnShift.started_at.desc())
        )
        if clamp_id is not None:
            query = query.where(BurnShift.clamp_id == clamp_id)
        shifts = list((await db.execute(query)).scalars().all())
        site_name = clamps[0].site.name if clamps else "乌石岗焖烧坞"
    return {
        "clamps": clamps,
        "shifts": shifts,
        "active_clamp_id": clamp_id,
        "status_labels": STATUS_LABELS,
        "site_name": site_name,
        "oxygen_counts": {c.id: len(c.oxygen_readings) for c in clamps},
    }


async def _load_oxygen_context(clamp_id: int | None = None) -> dict[str, Any]:
    async with SessionLocal() as db:
        clamps = list(
            (
                await db.execute(
                    select(Clamp)
                    .options(selectinload(Clamp.site), selectinload(Clamp.oxygen_readings))
                    .order_by(Clamp.code)
                )
            )
            .scalars()
            .all()
        )
        site_name = clamps[0].site.name if clamps else "乌石岗焖烧坞"
    selected: Clamp | None = None
    if clamp_id is not None:
        selected = next((c for c in clamps if c.id == clamp_id), None)
    if selected is None:
        selected = next((c for c in clamps if c.status == Clamp.STATUS_BURNING), None)
    if selected is None and clamps:
        selected = clamps[0]
    readings = sorted(selected.oxygen_readings, key=lambda r: r.seq) if selected else []
    next_seq = max((r.seq for r in readings), default=0) + 1
    return {
        "clamps": clamps,
        "burning_clamps": [c for c in clamps if c.status == Clamp.STATUS_BURNING],
        "selected_clamp": selected,
        "readings": readings,
        "next_seq": next_seq,
        "status_labels": STATUS_LABELS,
        "site_name": site_name,
    }


class AuthController(Controller):
    path = ""
    tags = ["auth"]

    @get("/login", media_type=MediaType.HTML)
    async def login_page(self, request: Request) -> Template:
        flash, flash_cat = _pop_flash(request)
        return Template(
            template_name="login.html",
            context={"flash": flash, "flash_cat": flash_cat},
        )

    @post("/login")
    async def login(
        self,
        request: Request,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        async with SessionLocal() as db:
            result = await db.execute(select(User).where(User.username == username))
            user = result.scalar_one_or_none()
            if not user or not verify_password(password, user.password_hash):
                request.set_session({"flash": "用户名或密码错误", "flash_cat": "error"})
                return Redirect("/login")
            request.set_session({"user_id": user.id})
        return Redirect("/")

    @get("/logout")
    async def logout(self, request: Request) -> Redirect:
        request.clear_session()
        return Redirect("/login")


class TimelineController(Controller):
    path = ""
    tags = ["timeline"]

    @get("/", media_type=MediaType.HTML)
    async def timeline(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        flash, flash_cat = _pop_flash(request)
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        ctx = await _load_timeline_context(clamp_id)
        return Template(
            template_name="timeline.html",
            context={
                **ctx,
                "user": request.user,
                "flash": flash,
                "flash_cat": flash_cat,
                "active_nav": "timeline",
            },
        )

    @get("/timeline/partial", media_type=MediaType.HTML)
    async def timeline_partial(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        ctx = await _load_timeline_context(clamp_id)
        return Template(
            template_name="partials/board.html",
            context={
                **ctx,
                "user": request.user,
            },
        )

    @get("/drawer/shift-new", media_type=MediaType.HTML)
    async def drawer_shift_new(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        async with SessionLocal() as db:
            clamps = list((await db.execute(select(Clamp).order_by(Clamp.code))).scalars().all())
        return Template(
            template_name="partials/drawer_shift.html",
            context={
                "clamps": clamps,
                "preselect_clamp_id": clamp_id,
                "user": request.user,
            },
        )

    @get("/drawer/clamp/{clamp_id:int}", media_type=MediaType.HTML)
    async def drawer_clamp(self, request: Request, clamp_id: int) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clamp)
                .where(Clamp.id == clamp_id)
                .options(
                    selectinload(Clamp.shifts),
                    selectinload(Clamp.site),
                    selectinload(Clamp.oxygen_readings),
                )
            )
            clamp = result.scalar_one_or_none()
            if not clamp:
                return Redirect("/")
        can_drawn, drawn_msg = can_mark_clamp_drawn(clamp)
        return Template(
            template_name="partials/drawer_clamp.html",
            context={
                "clamp": clamp,
                "status_labels": STATUS_LABELS,
                "can_drawn": can_drawn,
                "drawn_msg": drawn_msg,
                "oxygen_count": len(clamp.oxygen_readings),
                "user": request.user,
            },
        )


class ShiftController(Controller):
    path = "/shifts"
    tags = ["shifts"]

    @post("/new")
    async def create_shift(
        self,
        request: Request,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        if not request.user:
            return Redirect("/login")
        started_raw = data.get("started_at") or ""
        started_at = datetime.fromisoformat(started_raw) if started_raw else datetime.utcnow()
        peak_raw = (data.get("peak_temp_c") or "").strip()
        peak = float(peak_raw) if peak_raw else None
        clamp_id = int(data["clamp_id"])
        async with SessionLocal() as db:
            shift = BurnShift(
                clamp_id=clamp_id,
                started_at=started_at,
                peak_temp_c=peak,
                charcoal_grade=(data.get("charcoal_grade") or "B").strip(),
                notes=(data.get("notes") or "").strip(),
            )
            db.add(shift)
            clamp = (
                await db.execute(select(Clamp).where(Clamp.id == clamp_id))
            ).scalar_one_or_none()
            if clamp and clamp.status == Clamp.STATUS_STACKED:
                clamp.status = Clamp.STATUS_BURNING
            await db.commit()
        _set_flash(request, "焖烧班次已登记", "ok")
        return Redirect(f"/?clamp_id={clamp_id}")


class ClampController(Controller):
    path = "/clamps"
    tags = ["clamps"]

    @post("/{clamp_id:int}/status")
    async def set_status(
        self,
        request: Request,
        clamp_id: int,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        if not request.user:
            return Redirect("/login")
        new_status = (data.get("status") or "").strip()
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clamp)
                .where(Clamp.id == clamp_id)
                .options(selectinload(Clamp.shifts), selectinload(Clamp.oxygen_readings))
            )
            clamp = result.scalar_one_or_none()
            if not clamp:
                return Redirect("/")
            try:
                assert_can_set_clamp_status(clamp, new_status)
                clamp.status = new_status
                await db.commit()
                _set_flash(request, f"窑 {clamp.code} 状态已更新", "ok")
            except RuleError as exc:
                _set_flash(request, str(exc), "error")
        return Redirect(f"/?clamp_id={clamp_id}")


class OxygenController(Controller):
    path = "/oxygen"
    tags = ["oxygen"]

    @get("/", media_type=MediaType.HTML)
    async def oxygen_page(self, request: Request) -> Template | Redirect:
        if not request.user:
            return Redirect("/login")
        flash, flash_cat = _pop_flash(request)
        clamp_id = _parse_optional_int(request.query_params.get("clamp_id"))
        ctx = await _load_oxygen_context(clamp_id)
        return Template(
            template_name="oxygen.html",
            context={
                **ctx,
                "user": request.user,
                "flash": flash,
                "flash_cat": flash_cat,
                "active_nav": "oxygen",
            },
        )

    @post("/new")
    async def create_reading(
        self,
        request: Request,
        data: dict[str, Any] = Body(media_type=RequestEncodingType.URL_ENCODED),
    ) -> Redirect:
        if not request.user:
            return Redirect("/login")
        try:
            clamp_id = int(data.get("clamp_id") or "")
        except (TypeError, ValueError):
            _set_flash(request, "缺少有效的炭窑，无法登记测氧", "error")
            return Redirect("/oxygen")
        try:
            seq = int((data.get("seq") or "").strip())
        except (TypeError, ValueError):
            _set_flash(request, "测次须为整数，且从 1 起", "error")
            return Redirect(f"/oxygen?clamp_id={clamp_id}")
        try:
            oxygen_percent = float((data.get("oxygen_percent") or "").strip())
        except (TypeError, ValueError):
            _set_flash(request, "烟囱氧百分须为数字", "error")
            return Redirect(f"/oxygen?clamp_id={clamp_id}")
        sampled_raw = (data.get("sampled_at") or "").strip()
        try:
            sampled_at = datetime.fromisoformat(sampled_raw) if sampled_raw else utcnow()
        except ValueError:
            _set_flash(request, "采集时刻格式不正确", "error")
            return Redirect(f"/oxygen?clamp_id={clamp_id}")
        operator = (data.get("operator") or "").strip() or request.user.username
        async with SessionLocal() as db:
            result = await db.execute(
                select(Clamp)
                .where(Clamp.id == clamp_id)
                .options(selectinload(Clamp.oxygen_readings))
            )
            clamp = result.scalar_one_or_none()
            if not clamp:
                _set_flash(request, "炭窑不存在，无法登记测氧", "error")
                return Redirect("/oxygen")
            try:
                validate_oxygen_reading(clamp, seq, oxygen_percent)
            except RuleError as exc:
                _set_flash(request, str(exc), "error")
                return Redirect(f"/oxygen?clamp_id={clamp_id}")
            clamp_code = clamp.code
            db.add(
                OxygenReading(
                    clamp_id=clamp_id,
                    seq=seq,
                    oxygen_percent=oxygen_percent,
                    sampled_at=sampled_at,
                    operator=operator,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                # 两人同时交同一测次：唯一约束只放一笔落库，其余在此挡下。
                await db.rollback()
                _set_flash(
                    request,
                    f"窑 {clamp_code} 第 {seq} 次测氧刚被他人登记，本次提交被挡下，请刷新簿页核对测次",
                    "error",
                )
                return Redirect(f"/oxygen?clamp_id={clamp_id}")
        _set_flash(request, f"窑 {clamp_code} 第 {seq} 次测氧已登记", "ok")
        return Redirect(f"/oxygen?clamp_id={clamp_id}")
