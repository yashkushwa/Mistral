import requests
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ChatAction

model_prompts = {}
SELECTED_MODEL = "mistral-tiny"
api_keys = {}  # Store user-specific API keys

async def get_models(api_key):
    headers = {"Authorization": f"Bearer {api_key}"}
    response = requests.get("https://api.mistral.ai/v1/models", headers=headers)
    return [model['id'] for model in response.json()['data']]

def get_prompt_preview(prompt):
    if not prompt:
        return "No prompt set"
    lines = prompt.split('\n')
    return '\n'.join(lines[:2] + ['...'] if len(lines) > 2 else lines)

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Set API Key", callback_data="set_api_key")],
        [InlineKeyboardButton("Check Current API Key", callback_data="check_api_key")],
        [InlineKeyboardButton("Back to Models", callback_data="back_to_models")]
    ]
    await update.message.reply_text(
        "Settings Menu:\nManage your Mistral AI API key and other settings.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in api_keys:
        await update.message.reply_text(
            "Welcome! Please set up your Mistral AI API key first using /settings"
        )
        await settings_command(update, context)
        return

    keyboard = [[KeyboardButton("/start"), KeyboardButton("/settings")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    try:
        models = await get_models(api_keys[user_id])
        inline_keyboard = []
        for i in range(0, len(models), 2):
            row = [InlineKeyboardButton(models[i], callback_data=f"model_{models[i]}")]
            if i + 1 < len(models):
                row.append(InlineKeyboardButton(models[i + 1], callback_data=f"model_{models[i + 1]}"))
            inline_keyboard.append(row)
        inline_markup = InlineKeyboardMarkup(inline_keyboard)
        
        await update.message.reply_text(
            "Select a model:", 
            reply_markup=inline_markup
        )
    except Exception as e:
        await update.message.reply_text(
            "Error fetching models. Please check your API key in /settings"
        )

async def show_prompt_menu(update: Update, model_id):
    current_prompt = model_prompts.get(model_id, "")
    preview = get_prompt_preview(current_prompt)
    keyboard = [
        [InlineKeyboardButton("Set New Prompt", callback_data=f"set_{model_id}")],
        [InlineKeyboardButton("Clear Prompt", callback_data=f"clear_{model_id}")],
        [InlineKeyboardButton("Back to Models", callback_data="back_to_models")]
    ]
    text = f"Model: {model_id}\nCurrent prompt:\n{preview}"
    if isinstance(update, Update):
        await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global SELECTED_MODEL
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "set_api_key":
        await query.edit_message_text(
            "Please enter your Mistral AI API key:"
        )
        context.user_data['awaiting_api_key'] = True
    
    elif query.data == "check_api_key":
        api_key = api_keys.get(user_id, "No API key set")
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if api_key != "No API key set" else api_key
        keyboard = [[InlineKeyboardButton("Back to Settings", callback_data="back_to_settings")]]
        await query.edit_message_text(
            f"Your current API key: {masked_key}",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data == "back_to_settings":
        keyboard = [
            [InlineKeyboardButton("Set API Key", callback_data="set_api_key")],
            [InlineKeyboardButton("Check Current API Key", callback_data="check_api_key")],
            [InlineKeyboardButton("Back to Models", callback_data="back_to_models")]
        ]
        await query.edit_message_text(
            "Settings Menu:\nManage your Mistral AI API key and other settings.",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    elif query.data.startswith("model_"):
        SELECTED_MODEL = query.data.replace("model_", "")
        await show_prompt_menu(query, SELECTED_MODEL)
    
    elif query.data.startswith("set_"):
        model = query.data.replace("set_", "")
        await query.edit_message_text(f"Enter system prompt for {model}:")
        context.user_data['awaiting_prompt'] = model
    
    elif query.data.startswith("clear_"):
        model = query.data.replace("clear_", "")
        model_prompts[model] = ""
        await show_prompt_menu(query, model)
    
    elif query.data == "back_to_models":
        if user_id not in api_keys:
            await query.edit_message_text(
                "Please set up your API key first using /settings"
            )
            return
            
        try:
            models = await get_models(api_keys[user_id])
            keyboard = []
            for i in range(0, len(models), 2):
                row = [InlineKeyboardButton(models[i], callback_data=f"model_{models[i]}")]
                if i + 1 < len(models):
                    row.append(InlineKeyboardButton(models[i + 1], callback_data=f"model_{models[i + 1]}"))
                keyboard.append(row)
            await query.edit_message_text("Select a model:", reply_markup=InlineKeyboardMarkup(keyboard))
        except Exception as e:
            await query.edit_message_text(
                "Error fetching models. Please check your API key in /settings"
            )

async def stream_response(response):
    buffer = ""
    for chunk in response.iter_lines():
        if chunk:
            try:
                json_data = json.loads(chunk.decode('utf-8').replace('data: ', ''))
                if 'choices' in json_data:
                    content = json_data['choices'][0].get('delta', {}).get('content', '')
                    if content:
                        buffer += content
                        yield buffer
            except json.JSONDecodeError:
                continue

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if context.user_data.get('awaiting_api_key'):
        api_keys[user_id] = update.message.text
        del context.user_data['awaiting_api_key']
        # Delete the message containing the API key
        await update.message.delete()
        await update.message.reply_text(
            "API key has been set successfully! You can now use /start to begin using the bot."
        )
        return

    if 'awaiting_prompt' in context.user_data:
        model = context.user_data['awaiting_prompt']
        model_prompts[model] = update.message.text
        del context.user_data['awaiting_prompt']
        await show_prompt_menu(update, model)
        return

    if user_id not in api_keys:
        await update.message.reply_text(
            "Please set up your API key first using /settings"
        )
        return

    messages = []
    if SELECTED_MODEL in model_prompts and model_prompts[SELECTED_MODEL]:
        messages.append({"role": "system", "content": model_prompts[SELECTED_MODEL]})
    messages.append({"role": "user", "content": update.message.text})
    
    await update.message.chat.send_action(ChatAction.TYPING)
    
    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {api_keys[user_id]}",
            "Content-Type": "application/json"
        },
        json={
            "model": SELECTED_MODEL,
            "messages": messages,
            "stream": True
        },
        stream=True
    )

    initial_message = await update.message.reply_text("...")
    last_update_time = asyncio.get_event_loop().time()
    
    async for current_response in stream_response(response):
        current_time = asyncio.get_event_loop().time()
        if current_time - last_update_time >= 1.0:
            formatted_text = f"{current_response}\n\nUsing model: `{SELECTED_MODEL}`"
            try:
                await initial_message.edit_text(formatted_text, parse_mode='Markdown')
                last_update_time = current_time
            except Exception:
                continue
            await update.message.chat.send_action(ChatAction.TYPING)
    
    final_text = f"{current_response}\n\nUsing model: `{SELECTED_MODEL}`"
    await initial_message.edit_text(final_text, parse_mode='Markdown')

def main():
    app = ApplicationBuilder().token("7769194021:AAHb39XYKKc57vxKfUL5MHjICvgNsHijrVk").build()
    app.add_handler(CommandHandler('start', start_command))
    app.add_handler(CommandHandler('settings', settings_command))
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
