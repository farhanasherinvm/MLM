from django_filters import rest_framework as filters
from level.models import UserLevel

class PaymentFilter(filters.FilterSet):
    status = filters.ChoiceFilter(choices=UserLevel._meta.get_field('status').choices)
    approved_at__gte = filters.DateFilter(field_name='approved_at', lookup_expr='gte')
    approved_at__lte = filters.DateFilter(field_name='approved_at', lookup_expr='lte')

    class Meta:
        model = UserLevel
        fields = ['status', 'approved_at__gte', 'approved_at__lte']