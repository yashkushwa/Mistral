import requests
import asyncio
import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.constants import ChatAction

model_prompts = {}
SELECTED_MODEL = "mistral-tiny"

# Define prompt templates
PROMPT_TEMPLATES = {
    "themoji": "you have to talk in emoji only",
    "thecry": "You are gonna cry everytime in emoji"
}

async def get_models():
    headers = {"Authorization": f"Bearer q8YtsGpxpt5FHiheOfOLeJPN5N61D4AO"}
    response = requests.get("https://api.mistral.ai/v1/models", headers=headers)
    return [model['id'] for model in response.json()['data']]

def get_prompt_preview(prompt):
    if not prompt:
        return "No prompt set"
    lines = prompt.split('\n')
    return '\n'.join(lines[:2] + ['...'] if len(lines) > 2 else lines)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[KeyboardButton("/start")]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    models = await get_models()
    inline_keyboard = []
    for i in range(0, len(models), 2):
        row = [InlineKeyboardButton(models[i], callback_data=f"model_{models[i]}")]
        if i + 1 < len(models):
            row.append(InlineKeyboardButton(models[i + 1], callback_data=f"model_{models[i + 1]}"))
        inline_keyboard.append(row)
    inline_markup = InlineKeyboardMarkup(inline_keyboard)
    
    await update.message.reply_text("Welcome! Select a model:", reply_markup=inline_markup)

async def show_prompt_menu(update: Update, model_id):
    current_prompt = model_prompts.get(model_id, "")
    preview = get_prompt_preview(current_prompt)
    
    # Create template buttons
    keyboard = [
        [InlineKeyboardButton("Set New Prompt", callback_data=f"set_{model_id}")],
        [InlineKeyboardButton("💭 Themoji", callback_data=f"template_{model_id}_themoji"),
         InlineKeyboardButton("😢 TheCry", callback_data=f"template_{model_id}_thecry")],
        [InlineKeyboardButton("🔄 Reset Prompt", callback_data=f"clear_{model_id}"),
         InlineKeyboardButton("Back to Models", callback_data="back_to_models")]
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

    if query.data.startswith("model_"):
        SELECTED_MODEL = query.data.replace("model_", "")
        await show_prompt_menu(query, SELECTED_MODEL)
    
    elif query.data.startswith("template_"):
        # Handle template selection
        _, model, template_name = query.data.split("_")
        if template_name in PROMPT_TEMPLATES:
            model_prompts[model] = PROMPT_TEMPLATES[template_name]
            await show_prompt_menu(query, model)
    
    elif query.data.startswith("set_"):
        model = query.data.replace("set_", "")
        await query.edit_message_text(f"Enter system prompt for {model}:")
        context.user_data['awaiting_prompt'] = model
    
    elif query.data.startswith("clear_"):
        model = query.data.replace("clear_", "")
        model_prompts[model] = ""
        await show_prompt_menu(query, model)
    
    elif query.data == "back_to_models":
        models = await get_models()
        keyboard = []
        for i in range(0, len(models), 2):
            row = [InlineKeyboardButton(models[i], callback_data=f"model_{models[i]}")]
            if i + 1 < len(models):
                row.append(InlineKeyboardButton(models[i + 1], callback_data=f"model_{models[i + 1]}"))
            keyboard.append(row)
        await query.edit_message_text("Select a model:", reply_markup=InlineKeyboardMarkup(keyboard))

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
    if 'awaiting_prompt' in context.user_data:
        model = context.user_data['awaiting_prompt']
        model_prompts[model] = update.message.text
        del context.user_data['awaiting_prompt']
        await show_prompt_menu(update, model)
        return

    messages = []
    if SELECTED_MODEL in model_prompts and model_prompts[SELECTED_MODEL]:
        messages.append({"role": "system", "content": model_prompts[SELECTED_MODEL]})
    messages.append({"role": "user", "content": update.message.text})
    
    await update.message.chat.send_action(ChatAction.TYPING)
    
    response = requests.post(
        "https://api.mistral.ai/v1/chat/completions",
        headers={
            "Authorization": f"Bearer q8YtsGpxpt5FHiheOfOLeJPN5N61D4AO",
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
    app.add_handler(CallbackQueryHandler(button_callback))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot started...")
    app.run_polling()

if __name__ == "__main__":
    main()
