# ADR 0014: Wallet projections, reservations, and expiring credits

## Status
Accepted for Milestone 3-A1.

## Decision
Each wallet has a balance projection with posted, reserved, and available rial balances. Reservations reduce available balance by increasing reserved balance, but do not post ledger entries until a future order capture command is implemented. Credit lots preserve cash/non-cash bucket history and expiration; expiration is performed by a balanced financial command rather than editing original credits.

Spending priority is policy controlled and defaults to cash, refund, admin grant, gift, referral, then promotional credit. Expired credit is excluded from availability and remains historically visible.
