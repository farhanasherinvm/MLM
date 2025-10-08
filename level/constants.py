from decimal import Decimal

PAYMENT_CAP_AMOUNT = Decimal('4700.00') 
LOCK_LEVEL_NAME = 'Refer Help'
RESTRICTED_STATUS = 'Restricted'
CREDITED_STATUS = 'Credited'

# --- New PMF Tiers and Caps ---
PMF_PART_1_NAME = 'PMF Part 1'  # New Level/UserLevel name
PMF_PART_2_NAME = 'PMF Part 2'  # New Level/UserLevel name

PMF_PART_1_AMOUNT = Decimal('1000.00')
PMF_PART_2_AMOUNT = Decimal('1000.00')

CAP_1_AMOUNT = Decimal('15000.00') # Triggers PMF Part 1 payment
CAP_2_AMOUNT = Decimal('30000.00') # Triggers PMF Part 2 payment

# New Statuses for CustomUser.pmf_status field
PMF_STATUS_NOT_PAID = 'not_paid'
PMF_STATUS_PART_1_PAID = 'part_1_paid'
PMF_STATUS_PAID = 'fully_paid' # Both parts paid