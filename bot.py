import logging
import requests
import sqlite3
from datetime import datetime, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, CallbackQueryHandler,
    CallbackContext, JobQueue
)

# ===== CONFIGURATION ===== #
TOKEN = "8131770703:AAGI6gldE6abIxu6aUoVZ89aez2Jvil96cE"
ADMIN_ID = 6433950033
VIP_CHANNEL_ID = -1002480346068
NOWPAYMENTS_API_KEY = "8TSVVBH-DDGMS8S-HG9PC8Z-F3CM9RY"

# VIP Plans (USD)
PLANS = {
    "1month": {"price": 179, "days": 30, "name": "1 Month"},
    "3months": {"price": 399, "days": 90, "name": "3 Months"},
    "6months": {"price": 454, "days": 180, "name": "6 Months"},
    "12months": {"price": 699, "days": 365, "name": "12 Months"},
    "lifetime": {"price": 839, "days": 3650, "name": "Lifetime"}
}

# Initialize database
conn = sqlite3.connect('vip_bot.db', check_same_thread=False)
cursor = conn.cursor()

# ===== DATABASE SETUP ===== #
cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        join_date TEXT,
        expiry_date TEXT,
        is_vip BOOLEAN DEFAULT 0
    )
''')

cursor.execute('''
    CREATE TABLE IF NOT EXISTS payments (
        payment_id TEXT PRIMARY KEY,
        user_id INTEGER,
        plan_type TEXT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        payment_date TEXT,
        invoice_url TEXT,
        currency TEXT DEFAULT 'btc'
    )
''')
conn.commit()

# ===== PAYMENT FUNCTIONS ===== #
def create_nowpayments_invoice(user_id, plan_type):
    headers = {
        "x-api-key": NOWPAYMENTS_API_KEY,
        "Content-Type": "application/json"
    }
    
    payload = {
        "price_amount": float(PLANS[plan_type]["price"]),
        "price_currency": "usd",
        "pay_currency": "btc",
        "order_id": f"SKFALCON_{user_id}_{int(datetime.now().timestamp())}",
        "order_description": f"VIP {PLANS[plan_type]['name']} Access",
        "success_url": "https://t.me/SK_Falcon_VIP_Bot?start=success",
        "cancel_url": "https://t.me/SK_Falcon_VIP_Bot?start=cancel"
    }

    try:
        response = requests.post(
            "https://api.nowpayments.io/v1/invoice",
            headers=headers,
            json=payload,
            timeout=15
        )
        if response.status_code == 200:
            return response.json()
        logging.error(f"NowPayments Error: {response.text}")
    except Exception as e:
        logging.error(f"Payment error: {e}")
    return None

def check_payment_status(payment_id):
    headers = {"x-api-key": NOWPAYMENTS_API_KEY}
    try:
        response = requests.get(
            f"https://api.nowpayments.io/v1/payment/{payment_id}",
            headers=headers,
            timeout=10
        )
        return response.json().get('payment_status') == 'finished'
    except Exception as e:
        logging.error(f"Payment check failed: {e}")
        return False

# ===== BOT FUNCTIONS ===== #
def start(update: Update, context: CallbackContext):
    user = update.effective_user
    cursor.execute('INSERT OR IGNORE INTO users (user_id, username, join_date) VALUES (?, ?, ?)',
                 (user.id, user.username, datetime.now().strftime("%Y-%m-%d")))
    conn.commit()

    keyboard = [
        [InlineKeyboardButton("💎 VIP Subscription", callback_data="vip_subscribe")],
        [InlineKeyboardButton("🆘 Support", url="t.me/cryptofxskfalcon")]
    ]
    
    update.message.reply_text(
        "🦅 *Welcome to SK Falcon VIP Signals*\n\n"
        "🔮 Professional BTC trading alerts\n"
        "💎 VIP cryptocurrency signals\n\n"
        "Choose an option below:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

def vip_subscribe(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    buttons = [
        [InlineKeyboardButton(f"{details['name']} - ${details['price']}", callback_data=f"plan_{plan_id}")]
        for plan_id, details in PLANS.items()
    ]
    
    query.edit_message_text(
        "*💎 VIP Subscription Plans*\n\n"
        "🔐 Pay with Bitcoin (BTC)\n"
        "⚡ Instant access after confirmation\n\n"
        "Select your plan:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(buttons)
    )

def handle_plan_selection(update: Update, context: CallbackContext):
    query = update.callback_query
    plan_type = query.data.split('_')[1]
    user = query.from_user
    
    invoice = create_nowpayments_invoice(user.id, plan_type)
    if not invoice:
        query.edit_message_text("⚠️ Payment system unavailable. Try again later.")
        return
    
    # Extract invoice link safely
    invoice_url = invoice.get("invoice_url")
    if not invoice_url:
        query.edit_message_text("⚠️ Could not create payment invoice.")
        return

    # Extract payment ID from URL
    try:
        payment_id = invoice_url.split("iid=")[1].split("&")[0]  # Get iid parameter
    except (IndexError, AttributeError):
        query.edit_message_text("⚠️ Error processing payment link.")
        return

    # Save payment record with extracted ID
    cursor.execute('''
        INSERT INTO payments (
            payment_id, user_id, plan_type, amount,
            invoice_url, payment_date, currency
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        payment_id,
        user.id,
        plan_type,
        PLANS[plan_type]["price"],
        invoice_url,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'btc'
    ))
    conn.commit()
    
    query.edit_message_text(
        f"*BTC Payment for {PLANS[plan_type]['name']} VIP*\n\n"
        f"Amount: ${PLANS[plan_type]['price']} USD\n"
        f"Pay with: Bitcoin (BTC)\n"
        f"Payment ID: `{payment_id}`\n\n"
        "1. Click below to pay\n"
        "2. Send exact BTC amount\n"
        "3. Access granted after 1 confirmation",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("₿ Pay with BTC", url=invoice_url)],
            [InlineKeyboardButton("✅ Payment Done", callback_data=f"confirm_{payment_id}")]
        ])
    )

def verify_payments(context: CallbackContext):
    pending = cursor.execute('''
        SELECT payment_id, user_id, plan_type FROM payments 
        WHERE status = 'pending'
    ''').fetchall()
    
    for payment_id, user_id, plan_type in pending:
        if check_payment_status(payment_id):
            cursor.execute('UPDATE payments SET status = "completed" WHERE payment_id = ?', (payment_id,))
            
            expiry_date = datetime.now() + timedelta(days=PLANS[plan_type]["days"])
            cursor.execute('''
                INSERT OR REPLACE INTO users 
                (user_id, expiry_date, is_vip) 
                VALUES (?, ?, 1)
            ''', (user_id, expiry_date.strftime("%Y-%m-%d")))
            
            try:
                context.bot.unban_chat_member(VIP_CHANNEL_ID, user_id)
                context.bot.send_message(
                    chat_id=user_id,
                    text=f"🎉 *BTC Payment Confirmed!*\n\n"
                         f"You now have VIP {plan_type} access.\n"
                         f"Join: {VIP_CHANNEL_ID}",
                    parse_mode="Markdown"
                )
            except Exception as e:
                logging.error(f"VIP access failed: {e}")
            
            conn.commit()

# ===== MAIN FUNCTION ===== #
def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    
    updater = Updater(TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CallbackQueryHandler(vip_subscribe, pattern='vip_subscribe'))
    dp.add_handler(CallbackQueryHandler(handle_plan_selection, pattern='^plan_'))
    
    job_queue = updater.job_queue
    job_queue.run_repeating(verify_payments, interval=300, first=0)
    
    updater.start_polling()
    logging.info("🦅 BTC VIP Bot is now running with secure payment handling!")
    updater.idle()

if __name__ == '__main__':
    main()
