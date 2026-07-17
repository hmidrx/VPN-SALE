# ADR 0011: Money Representation

## Status
Accepted for Milestone 2-A.

## Decision
Store money as non-negative integers in the smallest configured canonical unit. The platform default is `IRR` rial. Persian UI may display toman by dividing rial by 10, but storage and APIs never silently mix rial and toman. No currency conversion is implemented.

## Consequences
Pricing avoids binary floating point and can apply safe integer addition, multiplication and rounding policies.
