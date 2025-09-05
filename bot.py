#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    BufferedInputFile
)

# Local core helpers
from wg_core import (
    ensure_root, ensure_paths, state_get, state_set,
    get_owner_id, set_owner_id,
    is_wireguard_ready, install_wireguard_quick,
    add_peer, revoke_peer, list_peers_text,
    get_peer_conf_path, make_qr_png,
    wg_restart, wg_stats_preformatted
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
if not BOT_TOKEN:
    raise SystemExit("BOT_TOKEN missing. Put it in .env")

# Must run as root to manage WireGuard
ensure_root()
ensure_paths()

router = Router(name="wgbot")

def main_menu(owner_set: bool) -> InlineKeyboardMarkup:
    rows = []
    if not owner_set:
        rows.append([InlineKeyboardButton(text="🔐 I’m the owner (set me)", callback_data="owner:claim")])
    else:
        rows.extend([
            [InlineKeyboardButton(text="🧰 Install/Check WireGuard", callback_data="wg:install")],
            [InlineKeyboardButton(text="➕ Add peer", callback_data="peer:add"),
             InlineKeyboardButton(text="📋 List peers", callback_data="peer:list")],
            [InlineKeyboardButton(text="🧾 Get config", callback_data="peer:cfg"),
             InlineKeyboardButton(text="🔳 QR code", callback_data="peer:qr")],
            [InlineKeyboardButton(text="🗑 Revoke peer", callback_data="peer:revoke"),
             InlineKeyboardButton(text="♻️ Restart WG", callback_data="wg:restart")],
            [InlineKeyboardButton(text="📈 Stats", callback_data="wg:stats"),
             InlineKeyboardButton(text="❓ Help", callback_data="help")],
        ])
    return InlineKeyboardMarkup(inline_keyboard=rows)

@router.message(CommandStart())
async def start(m: Message):
    await m.answer(
        "👋 <b>WireGuard VPN Manager</b>\n"
        "Everything works via buttons.\n\n"
        "First, set yourself as the owner.",
        parse_mode=ParseMode.HTML,
        reply_markup=main_menu(owner_set=(get_owner_id() is not None))
    )

def only_owner(user_id: int) -> bool:
    owner = get_owner_id()
    return owner is not None and owner == user_id

async def deny(cq: CallbackQuery):
    await cq.answer("Access denied", show_alert=True)

# ---------- Owner claim ----------
@router.callback_query(F.data == "owner:claim")
async def cb_owner_claim(cq: CallbackQuery):
    if get_owner_id() is None:
        set_owner_id(cq.from_user.id, cq.from_user.username or "")
        await cq.message.edit_text(
            f"✅ Owner set: <b>{cq.from_user.id}</b>\nNow you can manage the VPN.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu(owner_set=True)
        )
        await cq.answer("Owner saved")
    else:
        if not only_owner(cq.from_user.id):
            return await deny(cq)
        await cq.answer("Owner already set")

# ---------- WG install / check ----------
@router.callback_query(F.data == "wg:install")
async def cb_wg_install(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    ok, msg = install_wireguard_quick()
    await cq.message.answer(("✅ " if ok else "❌ ") + msg, parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- WG restart ----------
@router.callback_query(F.data == "wg:restart")
async def cb_wg_restart(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    ok, msg = wg_restart()
    await cq.message.answer(("✅ " if ok else "❌ ") + msg)
    await cq.answer()

# ---------- WG stats ----------
@router.callback_query(F.data == "wg:stats")
async def cb_wg_stats(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    text = wg_stats_preformatted()
    await cq.message.answer(text, parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Peers: list ----------
@router.callback_query(F.data == "peer:list")
async def cb_peer_list(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    await cq.message.answer(list_peers_text(), parse_mode=ParseMode.HTML)
    await cq.answer()

# Simple step memory in state file
def set_step(user_id: int, step: str, extra: dict | None = None):
    db = state_get()
    db.setdefault("steps", {})
    db["steps"][str(user_id)] = {"step": step, "extra": extra or {}}
    state_set(db)

def get_step(user_id: int):
    db = state_get()
    return db.get("steps", {}).get(str(user_id))

def clear_step(user_id: int):
    db = state_get()
    if "steps" in db:
        db["steps"].pop(str(user_id), None)
        state_set(db)

# ---------- Peers: add (button -> ask name) ----------
@router.callback_query(F.data == "peer:add")
async def cb_peer_add(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    if not is_wireguard_ready():
        return await cq.message.answer("⚠️ WireGuard not ready. Tap “🧰 Install/Check WireGuard” first.")
    set_step(cq.from_user.id, "await_name_add")
    await cq.message.answer("✍️ Send a name for the new peer (e.g., <code>iphone13</code>)", parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Peers: get config (button -> ask name) ----------
@router.callback_query(F.data == "peer:cfg")
async def cb_peer_cfg(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    set_step(cq.from_user.id, "await_name_cfg")
    await cq.message.answer("📦 Send peer name to get the <b>.conf</b> file", parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Peers: QR (button -> ask name) ----------
@router.callback_query(F.data == "peer:qr")
async def cb_peer_qr(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    set_step(cq.from_user.id, "await_name_qr")
    await cq.message.answer("🔳 Send peer name to get the <b>QR code</b>", parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Peers: revoke (button -> ask name) ----------
@router.callback_query(F.data == "peer:revoke")
async def cb_peer_revoke(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    set_step(cq.from_user.id, "await_name_revoke")
    await cq.message.answer("🗑 Send peer name to revoke", parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Help ----------
@router.callback_query(F.data == "help")
async def cb_help(cq: CallbackQuery):
    if not only_owner(cq.from_user.id): return await deny(cq)
    msg = (
        "❓ <b>Help</b>\n\n"
        "• 🧰 <b>Install/Check WireGuard</b> — sets up the server if missing\n"
        "• ➕ <b>Add peer</b> — create a new client (you’ll be asked for a name)\n"
        "• 📋 <b>List peers</b> — see all clients and their IPs\n"
        "• 🧾 <b>Get config</b> — sends a .conf file to import on desktop/mobile\n"
        "• 🔳 <b>QR code</b> — scan with the WireGuard app (iPhone 13 friendly)\n"
        "• 🗑 <b>Revoke peer</b> — remove a client’s access\n"
        "• ♻️ <b>Restart WG</b> — restart interface if endpoint/DNS changed\n"
        "• 📈 <b>Stats</b> — show handshakes & data usage\n\n"
        "Tip: Add your iPhone with a simple name like <code>iphone13</code> then tap 🔳 to scan.\n"
    )
    await cq.message.answer(msg, parse_mode=ParseMode.HTML)
    await cq.answer()

# ---------- Text handler for the step prompts ----------
@router.message(F.chat.type == ChatType.PRIVATE)
async def private_text(m: Message):
    owner_id = get_owner_id()
    if owner_id is None:
        return await m.answer("Tap “🔐 I’m the owner (set me)” first.", reply_markup=main_menu(owner_set=False))
    if not only_owner(m.from_user.id):
        return await m.answer("Access denied.")

    st = get_step(m.from_user.id)
    if not st:
        return await m.answer("Use the buttons below.", reply_markup=main_menu(owner_set=True))

    step = st["step"]
    name = (m.text or "").strip()
    if not name:
        return await m.answer("Send a valid name.")

    if step == "await_name_add":
        try:
            created_name, ip, _conf_path = add_peer(name)
            await m.answer(
                f"✅ Added <b>{created_name}</b> with IP <code>{ip}</code>\n"
                f"Use <b>🔳 QR code</b> or <b>🧾 Get config</b>.",
                parse_mode=ParseMode.HTML
            )
        except Exception as e:
            await m.answer(f"❌ {e}")
        finally:
            clear_step(m.from_user.id)

    elif step == "await_name_cfg":
        cpath = get_peer_conf_path(name)
        if not cpath:
            await m.answer("❌ No such peer.")
        else:
            data = cpath.read_bytes()
            await m.answer_document(
                BufferedInputFile(data, filename=f"{name}.conf"),
                caption=f"Config for <b>{name}</b>", parse_mode=ParseMode.HTML
            )
        clear_step(m.from_user.id)

    elif step == "await_name_qr":
        cpath = get_peer_conf_path(name)
        if not cpath:
            await m.answer("❌ No such peer.")
        else:
            try:
                png = make_qr_png(cpath)
                await m.answer_photo(
                    BufferedInputFile(png, filename=f"{name}.png"),
                    caption=f"QR for <b>{name}</b>", parse_mode=ParseMode.HTML
                )
            except Exception as e:
                await m.answer(f"❌ {e}")
        clear_step(m.from_user.id)

    elif step == "await_name_revoke":
        ok, msg = revoke_peer(name)
        await m.answer(("✅ " if ok else "❌ ") + msg)
        clear_step(m.from_user.id)

async def main():
    bot = Bot(BOT_TOKEN, parse_mode=ParseMode.HTML)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
