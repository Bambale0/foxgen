# Trace Map: Credits Check

Этот документ фиксирует, где система проверяет и меняет баланс пользователя.

## 1. Источники credit spend

- image generation
- video generation
- motion control
- avatar/video specialty flows
- video-to-prompt
- batch generation
- Mini App generation endpoints

## 2. Precondition flow

`user action`
-> resolve model/package/service cost
-> read current balance
-> compare against required credits
-> if insufficient:
  - stop launch
  - show top-up path
-> if sufficient:
  - continue to task/payment action

Основные cost sources:

- `data/price.json`
- `bot/services/preset_manager.py`
- `bot/quality_pricing.py`

## 3. Spend flow for generation

`validated generation request`
-> calculate normalized cost
-> create task record
-> deduct credits
-> save task payload / request metadata
-> attempt provider launch

Если launch падает до устойчивого async state:

- task should move to failed or equivalent safe state
- refund/rollback path must preserve balance integrity

## 4. Credit add flow

`verified successful payment`
-> transaction completion
-> `add_credits`
-> optional promo bonus
-> optional referral/partner side effects

## 5. Read surfaces for balance

- Telegram balance menu
- payment/package selection screens
- Mini App bootstrap
- task launch prechecks
- admin/finance views

## 6. Risk matrix

### Double spend

- repeated callback/button click
- duplicate webhook
- retry after network timeout

### Hidden spend mismatch

- UI shows old cost, backend uses new canonical alias cost
- duration/quality modifiers differ between screen and final service call

### Refund gaps

- provider launch failed after deduct
- orphan webhook closes wrong task

## 7. Practical verification points

- model cost resolution equals canonical alias mapping
- duration/quality modifiers match provider family
- insufficient balance blocks both bot and Mini App paths
- payment completion increments exactly once
