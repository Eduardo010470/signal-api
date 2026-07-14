import os
import stripe
import requests as req_lib
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

@app.route('/stripe-webhook', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    webhook_secret = os.environ.get('STRIPE_WEBHOOK_SECRET', '')
    stripe.api_key = os.environ.get('STRIPE_SECRET_KEY', '')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    supabase_url = os.environ.get('SUPABASE_URL', '')
    supabase_key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    headers = {
        'apikey': supabase_key,
        'Authorization': f'Bearer {supabase_key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=minimal'
    }

    try:
      event_type = event['type']
    except Exception as e:
      return jsonify({'error': 'invalid event'}), 400

    if event_type == 'checkout.session.completed':
        try:
            session = event.get('data', {}).get('object', {})
            email = session.get('customer_email') or session.get('customer_details', {}).get('email', '')
        except Exception as e:
            return jsonify({'error': str(e)}), 400
        customer_id = session.get('customer')
        subscription_id = session.get('subscription', '')
        if email:
            req_lib.patch(
                f'{supabase_url}/rest/v1/signal_users?email=eq.{email}',
                headers=headers,
                json={'is_premium': True, 'stripe_customer_id': customer_id}
            )
            req_lib.post(
                f'{supabase_url}/rest/v1/signal_subscriptions',
                headers={**headers, 'Prefer': 'resolution=merge-duplicates,return=minimal'},
                json={
                    'email': email,
                    'stripe_customer_id': customer_id,
                    'stripe_subscription_id': subscription_id,
                    'status': 'active'
                }
            )

    elif event['type'] == 'customer.subscription.deleted':
        subscription = event['data']['object']
        customer_id = subscription.get('customer')
        if customer_id:
            req_lib.patch(
                f'{supabase_url}/rest/v1/signal_users?stripe_customer_id=eq.{customer_id}',
                headers=headers,
                json={'is_premium': False}
            )
            req_lib.patch(
                f'{supabase_url}/rest/v1/signal_subscriptions?stripe_customer_id=eq.{customer_id}',
                headers=headers,
                json={'status': 'cancelled'}
            )

    elif event['type'] == 'invoice.payment_failed':
        invoice = event['data']['object']
        customer_id = invoice.get('customer')
        if customer_id:
            req_lib.patch(
                f'{supabase_url}/rest/v1/signal_users?stripe_customer_id=eq.{customer_id}',
                headers=headers,
                json={'is_premium': False}
            )

    return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
