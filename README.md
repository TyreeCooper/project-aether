# Project Aether

Paper-first Bitcoin (BTC/USD) operator console.

**Status:** Paper machine + public SMA rule + mobile-friendly web app. Live execution is blocked.

## What it does now

- Starts a paper ledger at $10,000 USD
- Polls a public BTC/USD mark
- Evaluates a published dual-SMA crossover (8 / 21) after warm-up
- Simulates fills with a fee so the blotter is not fantasy
- Lets you arm, pause, ticket, and flatten from a phone-sized layout

## Quick start

```bash
cp .env.example .env
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000 on a phone or browser.

Tap **Start** to arm the bot. It stays OFFLINE on process boot (fail closed).

## Rule under test

Long-only SMA cross on the public mark series. Stop at 2% below average entry. This rule may lose money. Paper exists to keep or kill it without live BTC.

## Safety

Do not set live keys. Do not treat paper equity as a forecast of live results.
