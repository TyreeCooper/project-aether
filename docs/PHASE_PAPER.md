# Paper machine (mobile app)

The platform now runs a paper-only loop:

- Public CoinGecko BTC/USD mark (no API keys)
- Dual SMA crossover (8/21) with a 2% software stop
- Simulated market fills and a 0.26% taker fee
- Start / stop / manual buy-sell / emergency flatten / flatten lock
- Mobile-first dashboard with a sticky flatten control

Live exchange execution is hard-blocked.
