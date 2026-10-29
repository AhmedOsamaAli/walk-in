"""Payments: Walk-in Founders' pledges and payouts, through PayPal.

paypal    the PayPal REST client (Orders v2, Payments v2, Payouts v1, Webhooks v1) and pure readers of its answers
pledges   founding-supporter campaigns: terms, progress, settlement, the AI-drafted pitch and the rules its words keep
records   campaigns and pledges from their rows, money in minor units, PayPal's refusals as HTTP answers, payout emails
founders  the seam that plugs the campaigns, the callbacks and the settlement loop into the app
"""
