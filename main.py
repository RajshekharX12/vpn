import json
import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from wireguard import generate_keys, generate_config
from qr import create_qr

BOT_TOKEN = "YOUR_TOKEN"

bot = Bot(BOT_TOKEN)
dp = Dispatcher()

servers = json.load(open("servers.json"))

@dp.message(Command("start"))
async def start(message: types.Message):

    kb = types.InlineKeyboardMarkup(inline_keyboard=[
        [types.InlineKeyboardButton(text="🇸🇬 Singapore", callback_data="singapore")],
        [types.InlineKeyboardButton(text="🇳🇱 Netherlands", callback_data="netherlands")],
        [types.InlineKeyboardButton(text="🇨🇭 Switzerland", callback_data="switzerland")],
        [types.InlineKeyboardButton(text="🇰🇷 South Korea", callback_data="korea")],
        [types.InlineKeyboardButton(text="🇮🇸 Iceland", callback_data="iceland")]
    ])

    await message.answer(
        "🌍 Choose VPN server:",
        reply_markup=kb
    )


@dp.callback_query()
async def server_selected(callback: types.CallbackQuery):

    server = servers[callback.data]

    private, public = generate_keys()

    config = generate_config(server, private, "10.0.0.10")

    qr = create_qr(config)

    await callback.message.answer_document(
        types.FSInputFile("config.conf")
    )

    await callback.message.answer_photo(
        types.FSInputFile(qr),
        caption="Scan this QR in WireGuard app"
    )

    await callback.answer()


async def main():
    await dp.start_polling(bot)

asyncio.run(main())
