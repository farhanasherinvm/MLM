from decimal import Decimal

# Total income caps
TOTAL_INCOME_CAPS = [
    Decimal('10000.00'),  # Child #1
    Decimal('20000.00'),  # Child #2
    Decimal('25000.00'),  # Child #3
    Decimal('35000.00'),  # Child #4
]

MAX_CHILDREN = len(TOTAL_INCOME_CAPS)

# Payment restriction statuses
RESTRICTED_STATUS = 'Restricted'
CREDITED_STATUS = 'Credited'
