import os
import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
import aiohttp


class BotState:
    """Хранение состояния для каждого пользователя"""
    def __init__(self):
        self.mode = 'greeting'
        self.sunrise = ''
        self.sunset = ''


# Хранилище состояний для разных пользователей
user_states = {}

def get_user_state(user_id: int) -> BotState:
    """Получаем или создаем состояние для пользователя"""
    if user_id not in user_states:
        user_states[user_id] = BotState()
    return user_states[user_id]


TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
OWM_API_KEY = os.environ.get("OWM_API_KEY")

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(bot)


async def fetch_geo_data(session: aiohttp.ClientSession, city: str) -> dict:
    """Запрос геоданных с проверкой ошибок"""
    geo_url = (
        "http://api.openweathermap.org/geo/1.0/direct"
        f"?q={city}&limit=1&appid={OWM_API_KEY}"
    )
    async with session.get(geo_url) as response:
        if response.status != 200:
            raise ValueError("Ошибка получения геоданных")

        data = await response.json()
        if not data:
            raise ValueError("Город не найден")

        return data[0]


async def fetch_weather_data(session: aiohttp.ClientSession, lat: float, lon: float) -> dict:
    """Запрос данных о погоде с проверкой ошибок"""
    weather_url = (
        "https://api.openweathermap.org/data/2.5/weather"
        f"?lat={lat}&lon={lon}&units=metric&appid={OWM_API_KEY}"
    )
    async with session.get(weather_url) as response:
        if response.status != 200:
            raise ValueError("Ошибка получения погоды")
        return await response.json()


async def send_weather(city: str, chat_id: int, user_id: int) -> None:
    """Основная логика получения и отправки погоды"""
    try:
        async with aiohttp.ClientSession() as session:
            # Получаем геоданные
            geo_data = await fetch_geo_data(session, city)

            # Получаем погоду
            weather = await fetch_weather_data(
                session,
                geo_data['lat'],
                geo_data['lon']
            )

            # Отправка иконки погоды
            icon_code = weather['weather'][0].get('icon', '')
            icon_url = f"http://openweathermap.org/img/wn/{icon_code}@4x.png"
            await bot.send_photo(chat_id, icon_url)

            # Формирование сообщения
            main_data = weather.get('main', {})
            wind_data = weather.get('wind', {})

            temp = main_data.get('temp', 'N/A')
            pressure = int(main_data.get('pressure', 0) * 0.75)
            wind = wind_data.get('speed', 'N/A')

            weather_message = (
                f"🌡 Температура: {temp}°C\n"
                f"📉 Давление: {pressure} мм рт.ст.\n"
                f"🌪 Ветер: {wind} м/с"
            )
            await bot.send_message(chat_id, weather_message)

            # Обработка времени
            sys_data = weather.get('sys', {})
            timezone = weather.get('timezone', 0)

            state = get_user_state(user_id)
            state.sunrise = datetime.utcfromtimestamp(
                sys_data.get('sunrise', 0) + timezone
            ).strftime('%H:%M')

            state.sunset = datetime.utcfromtimestamp(
                sys_data.get('sunset', 0) + timezone
            ).strftime('%H:%M')

            # Создание клавиатуры
            keyboard = types.InlineKeyboardMarkup(row_width=2)
            keyboard.add(
                types.InlineKeyboardButton('Да ✅', callback_data='yes'),
                types.InlineKeyboardButton('Нет ❌', callback_data='no'),
                types.InlineKeyboardButton('🔄 Начать заново', callback_data='start')
            )
            await bot.send_message(
                chat_id,
                "Показать время рассвета и заката?",
                reply_markup=keyboard
            )
            state.mode = 'sun_question'

    except Exception as error:
        error_message = "😢 Что-то пошло не так. Попробуйте другой город"
        if str(error) == "Город не найден":
            error_message = "🏙 Город не найден, попробуйте другой"

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton('🔄 Попробовать снова', callback_data='start'))
        await bot.send_message(chat_id, error_message, reply_markup=keyboard)


@dp.message_handler(commands=['start'])
async def start_command(message: types.Message) -> None:
    """Обработка команды /start"""
    state = get_user_state(message.from_user.id)
    state.mode = 'city_choice'

    cities = [
        ('🏙 Москва', 'Moscow'),
        ('🌆 Кейптаун', 'Cape Town'),
        ('🗽 Нью-Йорк', 'New York'),
        ('🌃 Шанхай', 'Shanghai'),
        ('✏️ Другой город', 'other'),
        ('🔄 Начать заново', 'start')
    ]

    keyboard = types.InlineKeyboardMarkup(row_width=2)
    for city_name, callback_data in cities:
        keyboard.add(types.InlineKeyboardButton(city_name, callback_data=callback_data))

    await message.answer("🌍 Выберите город:", reply_markup=keyboard)


@dp.message_handler(content_types=['text'])
async def text_message(message: types.Message) -> None:
    """Обработка текстовых сообщений"""
    state = get_user_state(message.from_user.id)
    if state.mode == 'other_city':
        await send_weather(
            message.text.strip(),
            message.chat.id,
            message.from_user.id
        )


@dp.callback_query_handler()
async def button_click(call: types.CallbackQuery) -> None:
    """Обработка нажатий кнопок"""
    user_id = call.from_user.id
    state = get_user_state(user_id)

    if call.data == 'start':
        await start_command(call.message)
        return

    if state.mode == 'city_choice':
        if call.data == 'other':
            await bot.send_message(
                call.message.chat.id,
                "📝 Введите название города:"
            )
            state.mode = 'other_city'
        else:
            await send_weather(
                call.data,
                call.message.chat.id,
                user_id
            )

    elif state.mode == 'sun_question':
        if call.data == 'yes':
            message_text = (
                f"🌅 Рассвет: {state.sunrise}\n"
                f"🌇 Закат: {state.sunset}"
            )
            await bot.send_message(call.message.chat.id, message_text)

        keyboard = types.InlineKeyboardMarkup()
        keyboard.add(types.InlineKeyboardButton('🔄 Начать заново', callback_data='start'))
        await bot.send_message(
            call.message.chat.id,
            "Хотите сделать новый запрос?",
            reply_markup=keyboard
        )
        state.mode = 'city_choice'


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
