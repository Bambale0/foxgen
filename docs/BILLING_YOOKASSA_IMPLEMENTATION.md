# YooKassa Billing Implementation

## Goal

Production payment flow for HappyFox with provider abstraction.

## Flow

User -> Mini App -> Payment Service -> Provider -> Webhook -> Verification -> Credit transaction -> Balance.

## Requirements

- Provider abstraction
- Idempotent webhook handling
- Immutable credit transactions
- PostgreSQL persistence
- Mini App checkout UX
- Admin audit trail

## Providers

- YooKassa
- Existing providers remain isolated behind the same contract

## Security

- Never trust webhook payload alone
- Verify payment status with provider API
- Prevent duplicate credit grants
- Keep payment audit history
